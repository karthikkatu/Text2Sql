# SQLTexter (Text2SQL): Codebase Architecture and Walkthrough

## Contents

1. [What the system does](#1-what-the-system-does)
2. [Repository map](#2-repository-map)
3. [System architecture](#3-system-architecture)
4. [Data model in FalkorDB](#4-data-model-in-falkordb)
5. [Flow A: application startup](#5-flow-a-application-startup)
6. [Flow B: connecting a database](#6-flow-b-connecting-a-database)
7. [Flow C: asking a question](#7-flow-c-asking-a-question)
8. [Backend walkthrough](#8-backend-walkthrough)
9. [Frontend walkthrough](#9-frontend-walkthrough)
10. [Python SDK and MCP server](#10-python-sdk-and-mcp-server)
11. [API and streaming protocol](#11-api-and-streaming-protocol)
12. [Security and reliability](#12-security-and-reliability)
13. [Configuration, testing and delivery](#13-configuration-testing-and-delivery)
14. [Issues found](#14-issues-found)
15. [Running it, including with Spider](#15-running-it-including-with-spider)

---

## 1. What the system does

SQLTexter turns a plain-English question into SQL, runs the SQL against the user's database, and explains the result in plain English.

Its central idea is that the database schema is stored as a **graph with vector embeddings**. Instead of sending the whole schema to the LLM, it searches that graph for the tables relevant to the question, adds the tables connected to them by foreign keys, and sends only that subset. This keeps prompts small on large schemas and brings in join tables the question never mentions.

| Layer | Technology |
|---|---|
| Backend | Python 3.12+, FastAPI, Uvicorn |
| Frontend | React 18, TypeScript, Vite 7, Tailwind CSS, Radix UI |
| Schema store | FalkorDB (a graph database that runs on Redis) |
| LLM access | LiteLLM: OpenAI, Gemini, Anthropic, Cohere, Azure, Ollama, or an OpenAI-compatible gateway |
| Conversation memory | Graphiti, stored in FalkorDB (OpenAI and Azure only) |
| SQL parsing | sqlglot |
| Target databases | PostgreSQL, MySQL, SQLite, Snowflake |
| Ways to use it | Web UI, REST API, MCP tools, Python SDK |
| Testing | pytest, Playwright |

**Size of the code**

| Area | Files | Lines |
|---|---:|---:|
| `api/` backend | 47 | 10,093 |
| `sqltexter/` SDK | 4 | 551 |
| `app/src/` frontend | 61 | 9,490 |
| `tests/` unit tests | 33 | 6,241 |
| `e2e/` browser tests | 13 | 3,358 |

---

## 2. Repository map

```text
api/                     Backend
├── index.py             Entry point: loads .env, creates the app, defines main()
├── app_factory.py       FastAPI setup: routers, MCP, middleware, static files
├── config.py            LLM provider detection, timeouts, shared prompts
├── extensions.py        Shared FalkorDB connection for the server
├── graph.py             Table retrieval: the find() function
├── embeddings.py        Runs embedding calls off the event loop
├── utils.py             LLM-written table and database descriptions
├── analytics.py         Writes unhandled errors to the Organizations graph
├── local_user.py        The single implicit user
├── agents/              One class per LLM task, plus retry logic in utils.py
├── core/
│   ├── text2sql.py      The pipeline: run_query, run_confirmed, get_schema
│   ├── pipeline.py      Pipeline helpers, including destructive-SQL detection
│   ├── schema_loader.py Connect-and-load flow, streaming and SDK versions
│   ├── result_models.py, request_models.py   Dataclasses shared with the SDK
│   ├── errors.py, db_resolver.py
├── loaders/             One loader per database, plus shared graph-writing code
├── memory/graphiti_tool.py   Long-term conversation memory
├── routes/              HTTP endpoints, streaming keepalive, usage tracking
├── sql_utils/           Quotes table names that contain special characters
└── helpers/             Credential redaction, HTTPS detection

app/src/                 React frontend
├── pages/               Index (main screen), Settings, NotFound
├── components/          chat/, schema/, modals/, layout/, ui/ (23 primitives)
├── contexts/            Auth, Database, Settings, Chat, QueryHighlight
├── services/            All HTTP calls: chat, database, auth, tokens, meta
├── utils/, lib/, config/, types/

sqltexter/               Python SDK: a thin wrapper over api.core
tests/                   pytest unit tests; tests/test_sdk/ holds integration tests
e2e/                     Playwright tests using page objects
docs/                    Loader and identifier-quoting notes
examples/                E-commerce example (SQL schema and Python script)
data/spider_data/        Spider benchmark, 166 databases (gitignored)
.github/workflows/       CI and publishing
Dockerfile, start.sh     Single image that runs FalkorDB and the app together
```

`spider_data.zip` (208 MB) in the repository root is untracked and not ignored, so a careless `git add .` would stage it.

---

## 3. System architecture

```mermaid
flowchart TB
    subgraph Clients
        UI["React web app"]
        SDK["Python SDK"]
        MCP["MCP clients"]
    end

    subgraph Server["FastAPI application"]
        MW["Security and CSRF middleware"]
        Routes["Routes: graphs, database, settings, meta"]
        MCPEP["/mcp endpoint"]
    end

    subgraph Core["Core logic (shared by server and SDK)"]
        Pipeline["Query pipeline: run_query, run_confirmed"]
        Find["Table retrieval: find"]
        Agents["LLM agents"]
        Safety["Destructive-SQL detection"]
        Loaders["Database loaders"]
        Memory["Memory tool (optional)"]
    end

    subgraph Stores["FalkorDB"]
        Schema[("Per-database schema graphs")]
        MemGraph[("Per-user memory graph")]
        Org[("Organizations graph")]
    end

    LLM["LLM and embedding provider, via LiteLLM"]
    Target[("User database: PostgreSQL, MySQL, SQLite, Snowflake")]

    UI --> MW --> Routes
    MCP --> MCPEP --> Routes
    Routes --> Pipeline
    Routes --> Loaders
    SDK --> Pipeline
    SDK --> Loaders
    Pipeline --> Find
    Pipeline --> Agents
    Pipeline --> Safety
    Pipeline --> Memory
    Pipeline --> Loaders
    Find --> Schema
    Find --> LLM
    Agents --> LLM
    Loaders --> Target
    Loaders --> Schema
    Memory --> MemGraph
    Routes --> Org
```

Four design decisions explain most of the code:

1. **One pipeline with several transports.** `run_query` is an async generator that yields progress events and ends with a `_Final(QueryResult)` marker ([text2sql.py:203](api/core/text2sql.py#L203)). The HTTP route streams the events. The SDK discards them through `collect_result` and returns the result. Because of this, the web UI, MCP and SDK can't drift apart.

2. **Blocking calls stay off the event loop.** LLM calls, embeddings and SQL execution are synchronous, so they run through `asyncio.to_thread`. The code comments trace this to a 2026-07-29 incident in which blocking calls stalled a live demo's stream.

3. **Unsafe until proven safe.** A generated statement only runs without confirmation if it can be shown to be read-only. Anything unparseable is treated as destructive.

4. **The SDK must install without the server.** Server-only imports such as Graphiti and Snowflake are deferred, and `api/routes`, `app_factory.py` and `index.py` are excluded from the wheel ([pyproject.toml:114](pyproject.toml#L114)).

---

## 4. Data model in FalkorDB

FalkorDB holds three kinds of graph. The live instance currently has `<user>_concert_singer`, `<user>-memory`, `Organizations` and `default_db`.

| Graph | Name | Purpose |
|---|---|---|
| Schema graph | `<user_id>_<db_name>` | One per connected database |
| Memory graph | `<user_id>-memory` | Long-term memory for one user |
| Organizations | `Organizations` (`ORGANIZATIONS_GRAPH`) | Error reports and usage events |

`user_id` is the base64 encoding of an email. With no login, it's always the base64 of `local@sqltexter.local`, which is `bG9jYWxAc3FsdGV4dGVyLmxvY2Fs`. Graphs whose names start with `GENERAL_PREFIX` are shared, read-only demo graphs.

### Schema graph

```mermaid
flowchart LR
    D["Database: name, description, url, user_rules"]
    T1["Table: name, description, embedding, foreign_keys"]
    C1["Column: name, type, nullable, key_type, description, embedding"]
    C2["Column in another table"]
    T2["Another Table"]
    C1 -- "BELONGS_TO" --> T1
    C2 -- "BELONGS_TO" --> T2
    C1 -- "REFERENCES: rel_name, note" --> C2
```

- The `Database` node isn't linked to the other nodes. It's found by label.
- `Table` and `Column` each have a vector index on `embedding` using Euclidean distance. `Table.name` also has an ordinary index.
- `Database.url` holds the full connection string, **including any password, in plain text**, because later queries reuse it to reach the database.
- `Table.foreign_keys` is stored as a JSON string.
- Column embeddings are computed before sample values are added, so sample values are visible to the LLM but don't affect vector search ([graph_loader.py:140](api/loaders/graph_loader.py#L140)).

### Memory graph

Graphiti's own `Entity` and `Episodic` nodes hold summaries and facts. The app adds two things: `HAS_DATABASE` links from a user entity to database entities, and `Query` nodes for past questions, attached to a database entity by `SUCCESS` or `FAILED` edges. `Query` nodes have embeddings so that similar past queries can be found.

### Organizations graph

`Error` nodes are written by `report_error`. The tracking code also expects `User` nodes, to which it would attach `UsageEvent` nodes, but nothing creates them any more (see [issue 8](#14-issues-found)).

---

## 5. Flow A: application startup

1. `uvicorn api.index:app` imports [api/index.py](api/index.py), which loads `.env` before any module reads the environment.
2. **Importing [config.py](api/config.py) selects the LLM provider.** The order is Ollama, OpenAI, Gemini, Anthropic, Cohere, and Azure as the fallback. Invalid timeouts stop startup with a clear error: zero, negative, `nan` and `inf` are all rejected because they'd remove the limit they configure ([config.py:112](api/config.py#L112)).
3. [`create_app`](api/app_factory.py#L199) then:
   - includes the routers, attaching `attach_local_user` as a router dependency
   - builds an MCP server from the routes tagged `mcp_tool`, unless `DISABLE_MCP` is set
   - creates a second FastAPI app combining the MCP and API routes
   - adds middleware, with security headers outermost so they also cover CSRF rejections
   - serves the built frontend from `app/dist`, with a catch-all route returning `index.html` for client-side routing
   - registers error handlers, turning unreachable-backend errors into HTTP 503 rather than 500
4. The FalkorDB connection pool in [extensions.py](api/extensions.py) is created lazily, the first time [`resolve_db`](api/core/db_resolver.py#L19) needs it. The server can therefore start while FalkorDB is down, and it reports the problem when a request needs the graph. The lazy import also lets the SDK use core code without creating this shared connection.

---

## 6. Flow B: connecting a database

This is the offline step that builds the schema graph.

```mermaid
sequenceDiagram
    actor User
    participant UI as DatabaseModal
    participant API as POST /database
    participant Loader as Database loader
    participant DB as User database
    participant LLM as LLM and embeddings
    participant Graph as FalkorDB

    User->>UI: Enter connection URL
    UI->>API: { url }
    API-->>UI: Step: starting
    API->>API: Check URL scheme, choose loader
    API-->>UI: Step: type detected
    API->>Loader: load(user_id, url)
    Loader->>DB: Read tables, columns, keys, sample values
    Loader->>Graph: load_to_graph(...)
    Graph->>LLM: Describe each table (batches of 10)
    Graph->>LLM: Describe the database
    Graph->>LLM: Embed tables and columns
    API-->>UI: Progress steps, then final_result
    UI->>UI: Refresh database list and select the new one
```

**Step by step**

1. [DatabaseModal](app/src/components/modals/DatabaseModal.tsx#L73) takes a URL, or builds one from separate fields, and posts it to `/database`.
2. [`load_database`](api/core/schema_loader.py#L101) returns a generator of progress messages. `_step_detect_db_type` rejects unknown URL schemes.
3. The loader reads the schema in a worker thread. [`run_introspection`](api/loaders/introspection.py#L41) uses a dedicated pool limited by `DB_SCHEMA_CONCURRENCY` (default 2), so a stalled database can't use up the threads other requests depend on.
4. For each table the loader collects column names, types, nullability, defaults, keys, foreign keys and three random sample values per column. Column descriptions are built from a template plus any database comment, not by the LLM.
5. [`load_to_graph`](api/loaders/graph_loader.py#L13) writes the graph in this order:
   1. Measure the embedding size by embedding a test string.
   2. Ask the LLM for a one-sentence description of each table, limited to 50 tokens. If a call fails, the table name is used instead.
   3. Create the vector indexes.
   4. Ask the LLM to describe the database, and create the `Database` node.
   5. Embed and create each `Table`, then its `Column` nodes in batches.
   6. Create a `REFERENCES` edge for each foreign key column.

**Cost to expect:** connecting makes at least one LLM call for every table, plus one for the database, plus at least one embedding call per table for its description and one per 100 columns.

---

## 7. Flow C: asking a question

This is the main path. `run_query` is at [text2sql.py:308](api/core/text2sql.py#L308).

```mermaid
sequenceDiagram
    actor User
    participant UI as ChatInterface
    participant API as POST /graphs/{id}
    participant P as run_query
    participant LLM
    participant G as FalkorDB
    participant DB as User database

    User->>UI: Question
    UI->>API: chat, result, flags
    API->>API: Validate before streaming
    P->>G: Read description, URL, user rules
    P->>LLM: RelevancyAgent
    alt Off-topic
        P-->>UI: followup_questions, stop
    end
    P->>LLM: find: describe the tables needed
    P->>LLM: Embed those descriptions
    P->>G: Vector search, FK neighbours, connecting paths
    opt Memory on
        P->>G: Search past queries and facts
    end
    P->>LLM: AnalysisAgent
    P-->>UI: sql_query (SQL, confidence, explanation)
    alt Not translatable
        P->>LLM: FollowUpAgent
        P-->>UI: followup_questions, stop
    else Destructive
        P-->>UI: destructive_confirmation, stop
    else Read-only
        P->>DB: Execute
        opt Execution fails
            P->>LLM: HealerAgent, up to 3 attempts
            P->>DB: Execute repaired SQL
        end
        P-->>UI: query_result
        P->>LLM: ResponseFormatterAgent
        P-->>UI: ai_response
        opt Memory on
            P->>G: Save in the background
        end
    end
```

### Step 1: The request

[`ChatInterface.handleSendMessage`](app/src/components/chat/ChatInterface.tsx#L106) calls [`ChatService.streamQuery`](app/src/services/chat.ts#L16). That function splits the conversation into two lists: `chat` (the user's questions, with the current one last) and `result` (the assistant's answers).

The route ([graphs.py:220](api/routes/graphs.py#L220)) validates the input **before** it starts streaming. `run_query` is a generator, so its own checks wouldn't run until streaming had begun and the HTTP status was already sent. This is what allows bad input to return a 400. History is limited to the last 5 questions (`SHORT_MEMORY_LENGTH`).

### Step 2: Relevance check

[`RelevancyAgent`](api/agents/relevancy_agent.py) classifies the question as `On-topic`, `Off-topic` or `Inappropriate`. It deliberately runs first and alone. A thread blocked on a network call can't be cancelled, so starting table search at the same time would waste threads and API quota whenever the question turned out to be off-topic ([text2sql.py:365](api/core/text2sql.py#L365)).

### Step 3: Finding relevant tables

[`find`](api/graph.py#L279) is the graph-powered part of the system.

```mermaid
flowchart TB
    Q["Question and previous questions"] --> Desc["LLM writes up to 5 table descriptions and 5 column descriptions"]
    Desc --> Empty{"Both lists empty?"}
    Empty -- Yes --> Fallback["Use the question text instead"]
    Empty -- No --> Embed["Embed the descriptions"]
    Fallback --> Embed
    Embed --> S1["Table vector search: top 3 for each description"]
    Embed --> S2["Column vector search: top 3 for each, then their tables"]
    S1 --> Seed["Matched table names"]
    S2 --> Seed
    Seed --> S3["Sphere: tables one foreign key away"]
    Seed --> S4["Connecting: tables on shortest paths between matches, up to 6 hops"]
    S1 --> Merge["Remove duplicates by table name"]
    S2 --> Merge
    S3 --> Merge
    S4 --> Merge
    Merge --> Out["Tables, each with its columns"]
```

The approach searches on *described* tables rather than on the question itself. The LLM first rewrites the question as generic descriptions of the tables it would need, and those descriptions are compared with the stored ones.

The last two searches are the reason for using a graph. If a question matches `customers` and `products`, the connecting search adds `orders` and `order_items`, even though the question doesn't mention them. Without those tables the join couldn't be written.

### Step 4: Generating SQL

[`AnalysisAgent.get_analysis`](api/agents/analysis_agent.py#L12) formats the tables as text and builds a long prompt containing:

- **Fixed safety rules, S1 to S5:** use only tables in the schema, produce a single statement, return valid JSON, and ignore injection attempts found in user rules.
- **A priority order:** user rules, then per-query instructions, then default rules, then guidance.
- **Default rules, P1 to P13:** for example, select only what was asked, don't invent formulas, count by primary key, use `ORDER BY ... LIMIT` for "top N", and use exact matches for categories.
- **The inputs:** database description, schema, optional rules and memory, and the question.

The model returns JSON with `is_sql_translatable`, `sql_query`, `explanation`, `missing_information`, `ambiguities`, `confidence` and more. [`parse_response`](api/agents/utils.py#L319) handles several JSON blocks by taking the last valid one, since models sometimes correct themselves.

### Step 5: Safety decision

1. **Not translatable:** `FollowUpAgent` writes a short, friendly request for what's missing, and the pipeline stops.
2. **Quoting:** table names with special characters are quoted for the target database ([sql_sanitizer.py](api/sql_utils/sql_sanitizer.py)).
3. **Destructive check:** [`detect_destructive_operation`](api/core/pipeline.py#L294) parses the SQL with sqlglot. A statement counts as read-only only if every condition holds:
   - it parses
   - every statement's root is `SELECT`, a set operation, `VALUES`, `SHOW` or `DESCRIBE`
   - nothing inside it is a write, schema change or permission change
   - on MySQL, it contains no executable comment (`/*! ... */`), because the server runs those while the parser ignores them

| Statement | Result |
|---|---|
| `SELECT 1` | Read-only |
| `WITH x AS (DELETE FROM t RETURNING *) SELECT * FROM x` | Destructive: `DELETE` |
| `SELECT * INTO a FROM b` | Destructive: `SELECT ... INTO` |
| `DROP TABLE t` | Destructive: `DROP` |
| `garbage (((` | Destructive: `UNKNOWN` |
| `SELECT pg_sleep(1)` | Read-only (a known limitation, see [section 12](#12-security-and-reliability)) |

Destructive SQL is refused outright on demo graphs. Otherwise the pipeline sends a `destructive_confirmation` event and stops, leaving the SQL unexecuted.

### Step 6: Execution and self-repair

The loader's `execute_sql_query` runs in a worker thread. If it fails, [`HealerAgent.heal_and_execute`](api/agents/healer_agent.py#L167) loops up to 3 times: it sends the failed SQL, the error and database-specific hints to the LLM, runs the result, and feeds any new error back.

The healer can't be used to bypass the safety check. Every repaired statement is checked again, and destructive repairs are rejected ([text2sql.py:542](api/core/text2sql.py#L542)).

### Step 7: The answer

[`ResponseFormatterAgent`](api/agents/response_formatter_agent.py) turns up to 50 result rows into a plain-language answer. The route records usage, and if memory is on, background tasks save the exchange without delaying the response.

### Confirming a destructive operation

When the user clicks Confirm, the UI posts the SQL with `confirmation: "CONFIRM"` to `/graphs/{id}/confirm`, handled by [`run_confirmed`](api/core/text2sql.py#L678). Any other value cancels. Confirmed SQL is never auto-repaired, because the user approved that exact statement. If the statement changes the schema, the graph is refreshed afterwards, although that refresh is currently broken for PostgreSQL and MySQL ([issue 1](#14-issues-found)).

### The agents

| Agent | Purpose | Temperature | Conversation history | Model override |
|---|---|---:|---|---|
| `find` (a function) | Describe the tables needed | 0 | Previous questions | **No** |
| `RelevancyAgent` | On-topic check | 0 | Yes | Yes |
| `AnalysisAgent` | Generate SQL | 0 | Yes | Yes |
| `FollowUpAgent` | Ask for missing information | 0.9 | No (context in prompt) | Yes |
| `HealerAgent` | Repair failed SQL | 0.1 | Own repair loop | **No** |
| `ResponseFormatterAgent` | Explain results | 0.3 | Stored, not sent | Yes |

---

## 8. Backend walkthrough

### LLM calls: `api/agents/utils.py`

[`run_completion`](api/agents/utils.py#L152) is the single path for LLM calls. It exists because of a stalled call with no timeout, and it has three properties:

- **One budget per call.** `LLM_TIMEOUT` (default 90 seconds) covers all attempts together, so retries can't extend the real limit.
- **Selective retries.** Timeouts, dropped connections, 408, 429 and 5xx are retried. A 401 or 400 is raised immediately, because replaying it can't help.
- **Respect for the provider.** A `Retry-After` header takes priority over the app's own backoff, and a retry that wouldn't fit in the remaining budget is skipped.

LiteLLM's and the provider SDK's own retries are turned off, because together they multiplied the effective timeout. `run_batch_completion` applies the same rules to a batch and retries only the items that failed for transient reasons.

### Loaders: `api/loaders/`

Each loader subclasses [`BaseLoader`](api/loaders/base_loader.py) and provides `load`, `execute_sql_query`, `refresh_graph_schema`, `is_schema_modifying_query` and `_execute_sample_query`.

| | PostgreSQL | MySQL | SQLite | Snowflake |
|---|---|---|---|---|
| Driver | psycopg2 | PyMySQL | Built-in `sqlite3` | snowflake-connector |
| URL | `postgresql://` or `postgres://` | `mysql://` | `sqlite:///path` | `snowflake://` |
| Metadata source | `information_schema`, `pg_*` | `information_schema` | `PRAGMA` | `SHOW` and `information_schema` |
| Can write? | Yes | Yes | **No, always read-only** | Yes |
| Query time limit | Server `statement_timeout`, TCP timeouts, and `deadline_guard` | Socket read and write timeouts | Progress handler (every 10,000 VM steps) | Server statement timeout, network and socket timeouts |

**PostgreSQL has the strictest limits.** The configured timeout acts as a ceiling a connection URL can tighten but not loosen ([postgres_loader.py:654](api/loaders/postgres_loader.py#L654)). `-c statement_timeout=0` in a URL can't turn it off.

[`deadline_guard`](api/loaders/deadline.py) covers the case those settings miss: a peer that holds the connection open without answering. A timer calls `shutdown()` on a duplicate of the socket, which makes the blocked read fail. The file explains why the more obvious options don't work: `conn.cancel()` can freeze the whole process, and `conn.close()` can deadlock on the driver's lock.

**SQLite is restricted to one directory.** Paths are resolved inside `SQLITE_DATA_DIR`, and anything outside is rejected ([sqlite_loader.py:79](api/loaders/sqlite_loader.py#L79)). This stops a URL such as `sqlite:////etc/hosts` from being used to read other files, which was confirmed by running it. Text is decoded leniently because some Spider databases contain non-UTF-8 bytes.

### Streaming: `api/routes/streaming.py`

The pipeline can be silent for a long time during SQL generation, and proxies tend to drop idle connections. [`with_keepalive`](api/routes/streaming.py#L29) sends a bare delimiter after every 10 seconds of silence. Clients already skip empty messages, so this needed no protocol change. A one-item queue applies backpressure, so a slow client can't cause the whole stream to pile up in memory.

### Memory: `api/memory/graphiti_tool.py`

Memory is optional and works only with OpenAI or Azure.

- **On read:** `search_memories` runs three searches at once (a user summary, database facts, and similar past queries) and combines them into a block of text. Past queries are separated into successes to learn from and failures to avoid.
- **On write:** after a response, background tasks save the query, update the summaries and prune old nodes. A failed save is logged but can't affect the response.
- **Expiry:** `MEMORY_TTL_SECONDS` can make memory graphs expire automatically.

### Other modules

| File | Role |
|---|---|
| [core/errors.py](api/core/errors.py) | `InternalError`, `GraphNotFoundError`, `InvalidArgumentError`, and the list of errors treated as transient |
| [core/db_resolver.py](api/core/db_resolver.py) | Returns the handle passed in, or else the server's shared connection |
| [routes/usage_tracking.py](api/routes/usage_tracking.py) | Records one usage event per query, in the background |
| [analytics.py](api/analytics.py) | Saves unhandled errors with credentials redacted |
| [helpers/redaction.py](api/helpers/redaction.py) | Removes passwords, tokens and URL credentials from text |
| [utils.py](api/utils.py) | Generates table and database descriptions |

---

## 9. Frontend walkthrough

### Structure

[App.tsx](app/src/App.tsx) nests providers in dependency order: `Auth`, `Database`, `Settings`, `Chat`, `QueryHighlight`. There are two real routes, `/` and `/settings`.

```mermaid
flowchart TB
    Index["pages/Index"] --> Sidebar["Sidebar"]
    Index --> TopBar["Inline top bar: database selector, refresh, delete"]
    Index --> Chat["ChatInterface"]
    Index --> Schema["SchemaViewer"]
    Index --> Modals["DatabaseModal, DeleteDatabaseModal, LoginModal"]
    Chat --> Msg["ChatMessage"]
    Chat --> Input["QueryInput"]
    Chat --> Svc["services/chat.ts"]
    Schema --> Canvas["@falkordb/canvas"]
    Schema --> Controls["SchemaCanvasControls"]
```

### State

| Context | Holds | Notes |
|---|---|---|
| `AuthContext` | User, sign-in providers | Calls `/auth-status`, which always says signed in. Retries every 15 seconds if the backend is down. |
| `DatabaseContext` | Database list and selection | Auto-selects the first database |
| `SettingsContext` | Vendor, model, API key | Vendor and model go in `localStorage`. **The API key stays in memory only.** |
| `ChatContext` | Messages and history | Clears when the selected database changes, so one database's history can't reach another |
| `QueryHighlightContext` | Selected query and its tables | Connects the chat to the schema view |

### Reading the stream

The response is a sequence of JSON objects separated by `|||FALKORDB_MESSAGE_BOUNDARY|||`. [`streamQuery`](app/src/services/chat.ts#L93) buffers incoming bytes, splits on the delimiter, keeps the possibly incomplete last piece for the next read, and yields each complete message. Empty pieces, including keepalives, are skipped.

`handleSendMessage` then acts on the message type: progress steps appear immediately, while SQL, results and the final answer are collected and rendered as cards at the end. Destructive confirmations are shown inline with Confirm and Cancel buttons.

### Schema viewer and query highlighting

[SchemaViewer](app/src/components/schema/SchemaViewer.tsx) draws tables and foreign-key links on an interactive canvas, using data from `GET /graphs/{id}/data`. Clicking "Show in schema" on a SQL card connects the two views:

1. [`extractTablesFromSQL`](app/src/utils/sqlTables.ts#L77) finds the table names in the SQL. It's a deliberate heuristic rather than a full parser, and it avoids traps such as treating the `FROM` in `EXTRACT(YEAR FROM ts)` as a table clause.
2. Those names go into `QueryHighlightContext`.
3. The schema panel opens and dims everything except those tables and the links between them.

### Settings

[Settings.tsx](app/src/pages/Settings.tsx) covers the bring-your-own API key, per-database rules (saved through `/graphs/{id}/user-rules`), and toggles for memory and rules. Keys are validated by `/settings/validate-api-key`, which makes one small test call and doesn't store the key.

### Leftover code

The frontend still carries much of the removed login system: `AuthModal`, `TokensModal`, large parts of `LoginModal` and `services/auth.ts`, and `services/tokens.ts`. See [issue 12](#14-issues-found).

---

## 10. Python SDK and MCP server

### SDK

[`SQLTexter`](sqltexter/client.py) runs the same pipeline in-process, without a web server. It still needs FalkorDB, an LLM provider, and the target database.

```python
import asyncio
from sqltexter import SQLTexter

async def main():
    async with SQLTexter(falkordb_url="redis://localhost:6379") as client:
        await client.connect_database("postgresql://user:pass@host/mydb")
        result = await client.query("mydb", "Show the top 5 customers by revenue")
        print(result.sql_query, result.results, result.ai_response)

        if result.requires_confirmation:
            await client.execute_confirmed("mydb", result.sql_query)

asyncio.run(main())
```

| Method | Purpose |
|---|---|
| `connect_database(url)` | Load a schema |
| `query(database, question)` | Accepts a string or a `QueryRequest` with history and options |
| `execute_confirmed(database, sql)` | Run approved destructive SQL |
| `get_schema`, `list_databases`, `delete_database`, `refresh_schema` | Manage schemas |
| `close()` | Waits for background saves, then closes the connection |

Each instance holds its own connection and passes it down through the `db` parameter, so several instances can coexist in one process. Differences from the server: memory defaults to off, and Snowflake isn't accepted by `connect_database`.

### MCP

[`create_app`](api/app_factory.py#L228) generates an MCP server from FastAPI routes at `/mcp`. Only routes tagged `mcp_tool` are exposed, and everything else is excluded by default.

| Tool | Route |
|---|---|
| `list_databases` | `GET /graphs` |
| `database_schema` | `GET /graphs/{id}/data` |
| `query_database` | `POST /graphs/{id}` |
| `connect_database` | `POST /database` |

The confirm route isn't exposed, so **an MCP client can't execute destructive SQL**. It can only receive the confirmation prompt. The local user is attached as a router dependency rather than middleware, because MCP calls reach the routes through an app object that the served app's middleware doesn't wrap ([local_user.py](api/local_user.py)).

---

## 11. API and streaming protocol

### Endpoints

| Method and path | Purpose | Response |
|---|---|---|
| `GET /graphs` | List databases | JSON |
| `GET /graphs/{id}/data` | Schema for the viewer | JSON `{nodes, links}` |
| `POST /graphs/{id}` | Ask a question | Stream |
| `POST /graphs/{id}/confirm` | Run or cancel destructive SQL | Stream |
| `POST /graphs/{id}/refresh` | Reload the schema | Stream |
| `DELETE /graphs/{id}` | Delete the schema graph (not the database itself) | JSON |
| `GET` and `PUT /graphs/{id}/user-rules` | Read or update per-database rules | JSON |
| `POST /graphs` | Upload a schema file | **Always 501, 415 or 422: not implemented** |
| `POST /database` | Connect a database | Stream |
| `POST /settings/validate-api-key` | Test an API key | JSON |
| `GET /version`, `GET /auth-status` | Metadata | JSON |
| `/mcp` | MCP tools | MCP protocol |
| `GET /docs`, `GET /redoc` | Interactive API docs | HTML |

All `POST`, `PUT` and `DELETE` requests except `/mcp` need the CSRF header.

### Query request

```json
{
  "chat": ["Earlier question", "Current question"],
  "result": ["Earlier answer"],
  "instructions": "Optional guidance for this query",
  "custom_api_key": "optional",
  "custom_model": "vendor/model",
  "use_user_rules": true,
  "use_memory": true
}
```

### Stream events

Each event is `JSON + |||FALKORDB_MESSAGE_BOUNDARY|||`. A delimiter with no JSON before it is a keepalive.

| `type` | Meaning | Main fields |
|---|---|---|
| `reasoning_step` | Progress | `message` |
| `sql_query` | Generated SQL and analysis | `data`, `conf`, `miss`, `amb`, `exp`, `is_valid` |
| `query_result` | Rows | `data` |
| `ai_response` | Final answer | `message` |
| `followup_questions` | Off-topic, or more detail needed | `message`, `missing_information`, `ambiguities` |
| `destructive_confirmation` | Approval needed | `message`, `sql_query`, `operation_type` |
| `operation_cancelled` | Confirmation declined | `message` |
| `healing_success` / `healing_failed` | Result of the repair loop | `healed_sql`, `attempts` / `final_error` |
| `schema_refresh` | Graph reload result | `message`, `refresh_status` |
| `final_result` | Connect or refresh finished | `success`, `message` |
| `error` | Failure, deliberately generic | `message` |

---

## 12. Security and reliability

### Security controls in place

| Threat | Control | Where |
|---|---|---|
| A website driving the local server through the browser | Double-submit CSRF cookie, compared in constant time | [app_factory.py:137](api/app_factory.py#L137) |
| Generated SQL changing data unnoticed | Detection that treats unknown statements as destructive, plus a confirmation step | [pipeline.py:294](api/core/pipeline.py#L294) |
| The healer writing to the database | Repaired SQL is re-checked | [text2sql.py:542](api/core/text2sql.py#L542) |
| Writes to demo databases | Refused, even when confirmed | [text2sql.py:693](api/core/text2sql.py#L693) |
| Reading arbitrary files through SQLite URLs | Paths confined to one directory, opened read-only | [sqlite_loader.py:52](api/loaders/sqlite_loader.py#L52) |
| Prompt injection through user rules | Fixed rules S4 and S5 in the prompt | [analysis_agent.py:265](api/agents/analysis_agent.py#L265) |
| Credentials in stored errors | Redaction | [redaction.py](api/helpers/redaction.py) |
| Internal details in responses | Generic error messages, details only in logs | [graphs.py:255](api/routes/graphs.py#L255) |
| Clickjacking, MIME sniffing, script injection | CSP and other security headers | [app_factory.py:32](api/app_factory.py#L32) |
| Credentials left in browser storage | API key kept in memory only | [SettingsContext.tsx:63](app/src/contexts/SettingsContext.tsx#L63) |

### Known limits

- **There is no authentication.** Anyone who can reach the server has full access, including running any SQL through `/confirm` once they hold a CSRF cookie, which any client can get just by making a request. [Issue 6](#14-issues-found) matters because of this.
- **Functions that look like reads aren't caught.** `SELECT my_mutating_function()` passes as read-only, since SQL shape alone can't reveal side effects. The code's own docstring says so ([pipeline.py:311](api/core/pipeline.py#L311)). **Use a read-only database account** where you don't intend writes.
- **Connection strings are stored in plain text** in the graph, as noted in section 4. Anyone with access to FalkorDB can read them.
- **Prompt rules are not a hard security boundary.** S4 and S5 depend on the model following them, whereas the sqlglot check and read-only credentials are enforced in code.

### Reliability controls

| Failure | Handling |
|---|---|
| LLM hangs | Total time budget per call |
| Temporary LLM errors | Bounded retries that respect `Retry-After` |
| Slow SQL blocks other users | Runs in worker threads |
| A query runs forever | Limits specific to each database (section 8) |
| A database hangs with the connection open | `deadline_guard` socket shutdown |
| A stalled schema load uses up threads | Dedicated pool limited to 2 by default |
| A proxy drops an idle stream | Keepalive every 10 seconds, plus anti-buffering headers |
| A client disconnects mid-stream | Cleanup that doesn't need to `await` |
| FalkorDB is unreachable | HTTP 503 rather than 500 |
| The model returns no table descriptions | Search with the question text instead |
| Background saves fail | Logged, with no effect on the response |

---

## 13. Configuration, testing and delivery

### Environment variables

The full list is in [.env.example](.env.example).

| Variable | Default | Purpose |
|---|---|---|
| `FALKORDB_URL` | `localhost:6379` | FalkorDB connection |
| `OPENAI_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, `COHERE_API_KEY`, `AZURE_API_KEY`, `OLLAMA_MODEL` | None | Set one to choose a provider |
| `OPENAI_API_BASE` | None | Use an OpenAI-compatible gateway |
| `COMPLETION_MODEL`, `EMBEDDING_MODEL` | Per provider | Override the models |
| `VOYAGE_API_KEY` | None | Embeddings for Anthropic, which has none of its own. Startup fails with Anthropic unless this or `EMBEDDING_MODEL` is set. |
| `LLM_TIMEOUT` | 90 s | Budget for one LLM call |
| `LLM_MAX_RETRIES` | 1 | Retries per call |
| `LLM_SLOW_CALL_THRESHOLD` | 20 s | Log a warning above this |
| `DB_CONNECT_TIMEOUT` | 10 s | Connection limit |
| `DB_STATEMENT_TIMEOUT` | 60 s | Query limit |
| `DB_SCHEMA_TIMEOUT` | 300 s | Schema-load limit |
| `DB_SCHEMA_CONCURRENCY` | 2 | Parallel schema loads |
| `SQLITE_DATA_DIR` | `<repo>/data` | Where SQLite files must be |
| `GENERAL_PREFIX` | None | Prefix for shared demo graphs |
| `DISABLE_MCP` | `false` | Turn off the MCP endpoint |
| `MEMORY_TTL_SECONDS` | None | Expiry for memory graphs |
| `HOST`, `PORT` | Varies, see issue 6 | Bind address |

The defaults differ across interfaces, which can be confusing:

| Setting | Web UI | REST API | SDK |
|---|---|---|---|
| Use memory | On | On | Off |
| Use saved rules | **Off** | **On** | On |

### Tests

There are 487 collected unit tests. Their subject matter reflects the project's priorities, with heavy coverage of safety and failure handling:

| Area | Files | What they verify |
|---|---|---|
| SQL safety | `test_destructive_detection`, `test_sql_sanitizer` | Bypass attempts, quoting |
| Timeouts and hangs | `test_db_execution_timeouts`, `test_deadline_guard`, `test_timeout_validation`, `test_stream_idle_timeout` | Limits can't be disabled |
| Event loop blocking | `test_find_offloading`, `test_embeddings_offloading`, `test_schema_load_offloading` | Slow calls run off the loop |
| LLM retries | `test_llm_retry_policy` | Budget and retry decisions |
| Streaming | `test_stream_keepalive` | Keepalives, disconnects |
| Security | `test_csrf_middleware`, `test_security_headers` | CSRF, headers |
| Loaders | `test_postgres_loader`, `test_mysql_loader`, `test_sqlite_loader`, `test_snowflake_loader`, `test_loader_contract` | Parsing and execution |
| Routes | `test_api_routes`, `test_settings_route`, `test_meta_route`, `test_transient_backend_errors` | Responses and status codes |
| Other | `test_usage_tracking`, `test_error_analytics`, `test_find_fallback`, `test_list_databases_order`, `test_dependency_holds` | Assorted behavior |
| SDK | `tests/test_sdk/` (23 tests) | Needs real services |

**What the tests don't catch:** most test files (18 of 28) use mocks, and the suite passes despite issues 1 to 3, which only appear when the real parts run together. There's also no evaluation code measuring SQL accuracy, even though the Spider benchmark is in `data/`.

E2E tests in `e2e/tests/` cover chat, database connection and the sidebar through page objects, about 33 tests. Those tagged `@requires-ai` need LLM credentials, and the rest always run in CI.

### Build and deployment

- **Docker:** one image contains both FalkorDB and the app. The frontend is built during the image build, and [start.sh](start.sh) starts Redis with the FalkorDB module, waits for it, then starts Uvicorn.
- **Local:** `make run-dev` builds the frontend and serves everything on port 5000. `npm run dev` in `app/` gives hot reload on port 8080, proxying `/api` to the backend.
- **Packaging:** `hatchling` builds the SDK wheel, which leaves out the server layer.

### CI/CD (`.github/workflows/`)

| Workflow | Trigger | Does |
|---|---|---|
| `tests.yml` | Push or PR to `main`, `staging` | Unit tests and lint, with a FalkorDB service |
| `playwright.yml` | Push or PR | E2E. AI tests only run when secrets are available. |
| `pylint.yml` | Any push | Python lint |
| `spellcheck.yml` | Push or PR to `main`, `staging` | Spell-checks `*.md` |
| `dependency-review.yml` | PR | Checks dependencies for known problems |
| `publish-docker.yml` | Release created | Pushes the image to Docker Hub |
| `publish-pypi.yml` | Release published | Publishes the SDK using trusted publishing, with no stored tokens |

No workflow runs `tsc`, which is how the type errors in issue 13 went unnoticed. Vite doesn't type-check during builds.

---

## 14. Issues found

**Confirmed by:**
- **Ran:** I executed the real code and observed the result.
- **Live:** I inspected the running FalkorDB instance with read-only queries.
- **Read:** I found it by reading the code, but did not trigger it.

Nothing was fixed, because this report only documents the code.

### High impact

| # | Issue | Effect | Confirmed |
|---|---|---|---|
| 1 | **Schema refresh after a schema change destroys the graph on PostgreSQL and MySQL.** `refresh_graph_schema` deletes the graph, then does `await Loader.load(...)`, but `load` is an async generator and can't be awaited. See [postgres_loader.py:632](api/loaders/postgres_loader.py#L632) and [mysql_loader.py:508](api/loaders/mysql_loader.py#L508). | After a confirmed `CREATE`, `ALTER` or `DROP`, the graph is gone and the database disappears from the app until it's reconnected. Running it gave `object async_generator can't be used in 'await' expression` after `graph.delete()` had already been called. | Ran |
| 2 | **Foreign-key details never reach the SQL generator.** [graph.py:397](api/graph.py#L397) turns foreign keys into a string, and [analysis_agent.py:155](api/agents/analysis_agent.py#L155) discards anything that isn't a dict. | The model sees a column marked `(FOREIGN KEY)` but not which table and column it references, so it has to guess join conditions. This probably reduces accuracy on multi-table questions, though that effect wasn't measured. It's also the data the project's graph design exists to provide. | Ran |
| 3 | **Reconnecting or refreshing duplicates the schema graph.** `load_to_graph` always uses `CREATE`, and `POST /refresh` doesn't clear the graph first. | The live `concert_singer` graph has 8 `Table` nodes for 4 real tables, and 2 `Database` nodes. Each vector search returns 3 results, so duplicates push out other relevant tables. The UI hides this because it removes duplicates by name. | Live |

### Medium impact

| # | Issue | Effect | Confirmed |
|---|---|---|---|
| 4 | **Column key data is written and read under different names.** The loader writes `key_type` ([graph_loader.py:154](api/loaders/graph_loader.py#L154)), but `find` reads `columns.key`, and the connecting search compares against `'PRI'`, a value loaders no longer write. | Column keys always read as null, so the prompt shows `(int,,None,NO)`. The `(PRIMARY KEY)` text in the description partly makes up for this. | Live |
| 5 | **Non-JSON model output crashes the request.** `parse_response` has a fallback result, but it lacks the fields callers need. See [analysis_agent.py:45](api/agents/analysis_agent.py#L45) and [text2sql.py:379](api/core/text2sql.py#L379). | `KeyError: 'ambiguities'` in the analysis agent, and the relevancy result has no `status` key. The user gets a generic internal error rather than the intended graceful handling. | Ran |
| 6 | **The unauthenticated server listens on all interfaces in some modes.** The docs say it binds to `127.0.0.1`, but [start.sh:30](start.sh#L30) and [Makefile:90](Makefile#L90) (`run-prod`) default to `0.0.0.0`. | On a shared network, others can reach it and run SQL with the stored credentials. Docker's port publishing has a similar effect. | Read |
| 7 | **The AGPL `LICENSE` file is deleted in the working tree,** and the README links to a "License and attribution" section that doesn't exist. `pyproject.toml` still declares AGPL. | The code derives from an AGPL project, whose licence requires passing on a copy of it. Restore it before distributing. This is a compliance flag rather than legal advice. | Ran |
| 8 | **Usage tracking records nothing.** It starts with `MATCH (u:User {email})`, but with auth removed nothing creates `User` nodes. | The live `Organizations` graph has 0 `User` nodes, so no `UsageEvent` is ever saved, and no error is raised. | Live |
| 9 | **Memory searches use the wrong text.** [graphiti_tool.py:547](api/memory/graphiti_tool.py#L547) overwrites the `query` parameter with a Cypher string, which is then used as the search text. | Database-fact search looks for the Cypher text rather than the user's question, so its results are unlikely to be relevant. | Read |
| 10 | **Text is inserted directly into Cypher in the memory code.** [graphiti_tool.py:359](api/memory/graphiti_tool.py#L359) escapes quotes but not backslashes. | A question ending in `\` could break the query or alter it. The impact is limited to the memory graph. Parameters would avoid this. | Read |
| 11 | **Docker runs with auto-reload on by default.** At [start.sh:23](start.sh#L23), `${FASTAPI_DEBUG:-true}` makes the check true when the variable is unset. | Uses more resources and isn't suited to production use. | Read |

### Low impact

| # | Issue | Confirmed |
|---|---|---|
| 12 | **Dead frontend code:** no backend routes exist for `/upload`, `/login/*`, `/signup/*`, `/logout` or `/tokens/*`. `AuthModal`, `TokensModal` and `layout/Header.tsx` are never imported. `POST /graphs` always fails, as its loaders were never implemented. | Read |
| 13 | **`tsc` fails:** a deprecated `baseUrl` config error, then 7 type errors once that's bypassed. CLAUDE.md describes strict TypeScript, but nothing enforces it. | Ran |
| 14 | **Healed SQL isn't shown.** The UI ignores `healing_success`, so it displays the original failed SQL beside the results of the repaired one. | Read |
| 15 | **A success toast appears after errors.** "Query Complete" shows even after an error event ([ChatInterface.tsx:296](app/src/components/chat/ChatInterface.tsx#L296)). | Read |
| 16 | **User-supplied API keys aren't used everywhere.** `find` and the healer always use the server's key and model, so a browser-supplied key alone isn't enough. | Read |
| 17 | **Wrong graph name on refresh.** Refresh rebuilds the name by splitting on `_`, so `concert_singer` becomes `concert_concert_singer`. It's reachable on Snowflake today, and would surface on PostgreSQL and MySQL once issue 1 is fixed. | Ran (name calculation only) |
| 18 | **Import order matters.** `import api.loaders.sqlite_loader` fails with a circular-import error unless `api.core` is imported first. Normal startup is unaffected. | Ran |
| 19 | **Wasted work without memory support.** On unsupported providers, each query still makes an LLM summary call, and `clean_memory` fails on a null client (the error is logged). | Read |
| 20 | **SQLite offers writes it can't perform.** The agent generates a write and asks for confirmation, then it fails with `attempt to write a readonly database`. The data stays safe, but the experience is confusing. | Ran |
| 21 | **Outdated text and leftovers:** CLAUDE.md lists `api/entities/` and `api/analyzers/`, which don't exist. `authlib`, `itsdangerous` and `jinja2` are still dependencies but aren't imported. `Text_To_SQL_PROMPT`, `DB_MAX_DISTINCT` and `DB_UNIQUENESS_THRESHOLD` are unused. `QueryMetadata.confidence` is documented as 0 to 1, while the prompt asks for 0 to 100. `.env.example` contradicts itself on whether `LLM_TIMEOUT` is per attempt or in total; the code treats it as the total. | Read |
| 22 | **Demo logic is hardcoded in the frontend:** it checks for `general_` rather than the configurable `GENERAL_PREFIX`, so the two can disagree. | Read |

### Suggested fix order

1. **Issue 7:** restore `LICENSE`, since it's quick and matters for distribution.
2. **Issues 2, 3 and 4:** these directly affect SQL quality, so fix them before measuring accuracy on Spider. Otherwise the baseline will understate what the design can do.
3. **Issue 1, then 17:** these prevent data loss and should go together.
4. **Issues 5 and 6:** these address robustness and exposure.
5. **Add one integration test** that loads a real SQLite database and checks the resulting prompt, as it would have caught issues 2, 3 and 4.

---

## 15. Running it, including with Spider

```bash
make install                # Install Python and Node dependencies
cp .env.example .env        # Then set FALKORDB_URL and one LLM provider
make docker-falkordb        # Start FalkorDB in Docker
make run-dev                # Build the frontend and serve at http://localhost:5000
```

Useful commands:

```bash
make test-unit              # Unit tests
make test-e2e-no-ai         # Browser tests that need no LLM credentials
make lint                   # pylint and ESLint
```

### Using the Spider benchmark

The dataset is at `data/spider_data/`, with 166 databases and the `dev.json`, `dev_gold.sql` and `tables.json` benchmark files. Because `SQLITE_DATA_DIR` defaults to `<repo>/data`, a database can be connected from the UI by choosing SQLite and entering:

```text
sqlite:///spider_data/database/concert_singer/concert_singer.sqlite
```

Direct execution with this URL was tested on `concert_singer`: a `SELECT` worked and returned 6 singers, while a `DELETE` was refused and the data was unchanged.

The graph is named `<user_id>_concert_singer` and appears in the UI as `concert_singer`. Each connection makes LLM calls, as described in section 6, so loading all 166 databases has a real cost. Connect each one only once, because of issue 3.

**The repository has no evaluation harness.** Measuring accuracy would need a script that loads the databases through `SQLTexter.connect_database`, runs each question in `dev.json` through `query`, and compares the results against `dev_gold.sql`. The official Spider evaluation script isn't part of this codebase.
