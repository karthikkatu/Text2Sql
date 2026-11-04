<div align="center">  
  <h1>SQLTexter (Text2SQL)</h1>

**REST API · MCP · Graph-powered** 

SQLTexter is an **open-source Text2SQL** tool that converts plain-English questions into SQL using **graph-powered schema understanding**. It helps you ask databases natural-language questions and returns SQL and results.

Connect and ask questions: [![Discord](https://img.shields.io/badge/Discord-%235865F2.svg?&logo=discord&logoColor=white)](https://discord.gg/b32KEzMzce)

[![Try Free](https://img.shields.io/badge/Try%20Free-FalkorDB%20Cloud-FF8101?labelColor=FDE900&link=https://app.falkordb.cloud)](https://app.falkordb.cloud)
[![Tests](https://github.com/karthikkatu/Text2Sql/actions/workflows/tests.yml/badge.svg?branch=main)](https://github.com/karthikkatu/Text2Sql/actions/workflows/tests.yml)
</div>



## Run the UI with the Spider dataset

Follow these steps to go from a copy of this repository to asking questions about a [Spider](https://yale-lily.github.io/spider) database in your browser. The dataset isn't included in the repository, so you download it first.

The commands are for macOS or Linux. Run them from the repository root.

### Prerequisites

- [uv](https://docs.astral.sh/uv/getting-started/installation/), which also installs Python 3.12+ if you don't have it
- Node.js 20.19+ or 22.12+, with npm
- Docker, installed and running
- `make` and `unzip`
- An API key for one LLM provider, or a local Ollama model (see [step 4](#4-configure-your-llm-provider))
- About 2 GB of free disk space

### 1. Download the Spider dataset

1. Open the Spider page: https://yale-lily.github.io/spider
2. Click the **Spider Dataset** link, which opens the file on Google Drive, and download it.
3. Move the downloaded `spider_data.zip` (about 200 MB) to the repository root.

> Spider is distributed under the [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/legalcode) license.

### 2. Extract it into `data/`

```bash
mkdir -p data
unzip spider_data.zip -d data
rm -rf data/__MACOSX spider_data.zip
```

SQLTexter only opens SQLite files inside `data/`, and always read-only. Check that the files are in the right place:

```bash
ls data/spider_data/database/concert_singer
# concert_singer.sqlite  schema.sql
```

### 3. Install dependencies

```bash
make install
```

### 4. Configure your LLM provider

```bash
cp .env.example .env
```

Open `.env` and add a key for one provider. For example, for OpenAI:

```bash
OPENAI_API_KEY=your_openai_api_key
```

For other providers, see [AI/LLM configuration](#aillm-configuration). For an OpenAI-compatible gateway, set these four values instead:

```bash
OPENAI_API_KEY=your_gateway_key
OPENAI_API_BASE=https://your-gateway.example.com/v1
COMPLETION_MODEL=openai/<completion-model>
EMBEDDING_MODEL=openai/<embedding-model>
```

> If your embedding model doesn't produce 1536-dimension vectors, the server log shows `Vector dimension mismatch` errors for each question. Answers in the UI still work, but SQLTexter can't look up similar past questions.

Leave `FALKORDB_URL` as it is. The default matches the container you start in the next step.

### 5. Start FalkorDB

```bash
make docker-falkordb
```

### 6. Start the app

```bash
make run-dev
```

This builds the frontend and starts the server. When the log shows `Application startup complete`, leave the terminal running and open http://127.0.0.1:5000 in your browser. There's no login.

> On macOS, use `127.0.0.1` rather than `localhost`. AirPlay Receiver also listens on port 5000, so `localhost:5000` can return a `403` error from AirPlay instead of loading the app.

### 7. Connect a Spider database

1. Click **Connect to Database**.
2. Under **Database Type**, choose **SQLite**.
3. Under **Connection URL**, enter:

   ```text
   sqlite:///spider_data/database/concert_singer/concert_singer.sqlite
   ```
4. Click **Connect**.

When it finishes, the header shows **Connected: concert_singer**. This took about 15 seconds in testing, and uses your LLM provider.

To use another database, replace both instances of `concert_singer` with a folder name from `data/spider_data/database/`.

> Connect each database only once, and don't use the refresh button next to the database selector. Either one currently duplicates the schema graph, which can lower SQL quality.

### 8. Ask a question

Type a question in the box at the bottom of the page and press the send button. For example:

```text
How many singers do we have?
```

You should see the generated SQL, a results table with the value `6`, and an answer in plain English. The SQL can vary between runs and LLM models, for example:

```sql
SELECT COUNT(Singer_ID) FROM singer;
```

To try more questions and compare your results with the expected SQL, see `dev.json` and `dev_gold.sql` in `data/spider_data/`.

### Stop and restart

Press `Ctrl+C` in the server terminal, then stop FalkorDB:

```bash
docker stop falkordb-test
```

To start again, your connected databases are still there:

```bash
docker start falkordb-test
make run-dev
```

`make docker-stop` also stops FalkorDB, but it removes the container, so you'd need to run step 5 and connect your databases again.

### Common problems

| Problem | Fix |
|---------|-----|
| `403` error at `localhost:5000` on macOS | Open http://127.0.0.1:5000 instead. |
| Port 5000 is already in use | Run `PORT=5001 make run-dev` and open http://127.0.0.1:5001. |
| `Failed to load database schema` when connecting | If the server log shows `Invalid SQLite database path`, check that the URL starts with `sqlite:///spider_data/` and that the file from step 2 exists. |
| `make docker-falkordb` says the container name is already in use | The container already exists. Run `docker start falkordb-test`. |
| Connecting or asking a question fails with an LLM error | Check the key and model names in `.env`, then restart the server. |

## Get Started

### Docker

> 💡 Recommended for evaluation purposes (Local Python or Node are not required)
```bash
docker build -t sqltexter .
docker run -p 5000:5000 -it sqltexter
```


Launch: http://localhost:5000

---

### Use an .env file (Recommended)

Create a local `.env` by copying `.env.example` and passing it to Docker. This is the simplest way to provide all required configuration:

```bash
cp .env.example .env
# edit .env to set your values, then:
docker run -p 5000:5000 --env-file .env sqltexter
```

### Alternative: Pass individual environment variables

If you prefer to pass variables on the command line, use `-e` flags (less convenient for many variables):

```bash
docker run -p 5000:5000 -it \
  -e FALKORDB_URL=redis://host.docker.internal:6379/0 \
  -e AZURE_API_KEY=your_azure_api_key \
  sqltexter
```

> SQLTexter has no login: anyone who can reach the server is the same user.
> Keep it on localhost or a network you trust.

> Note: SQLTexter supports multiple AI providers. You can use `OPENAI_API_KEY`, `GEMINI_API_KEY`, `ANTHROPIC_API_KEY`, or `AZURE_API_KEY`. See the [AI/LLM configuration](#aillm-configuration) section for details.

> For a full list of configuration options, consult `.env.example`.

## Memory TTL (optional)

SQLTexter stores per-user conversation memory in FalkorDB. By default these graphs persist indefinitely. Set `MEMORY_TTL_SECONDS` to apply a Redis TTL (in seconds) so idle memory graphs are automatically cleaned up.

```bash
# Expire memory graphs after 1 week of inactivity
MEMORY_TTL_SECONDS=604800
```

The TTL is refreshed on every user interaction, so active users keep their memory.

## MCP server: host or connect (optional)

SQLTexter includes optional support for the Model Context Protocol (MCP). You can either have SQLTexter expose an MCP-compatible HTTP surface (so other services can call SQLTexter as an MCP server), or configure SQLTexter to call an external MCP server for model/context services.

What SQLTexter provides
- The app registers MCP operations focused on Text2SQL flows:
   - `list_databases`
   - `connect_database`
   - `database_schema`
   - `query_database`

- To disable the built-in MCP endpoints set `DISABLE_MCP=true` in your `.env` or environment (default: MCP enabled).
- Configuration

- `DISABLE_MCP` — disable SQLTexter's built-in MCP HTTP surface. Set to `true` to disable. Default: `false` (MCP enabled).

Examples

Disable the built-in MCP when running with Docker:

```bash
docker run -p 5000:5000 -it --env DISABLE_MCP=true sqltexter
```

Calling the built-in MCP endpoints (example)
- The MCP surface is exposed as HTTP endpoints. 


### Server Configuration

Below is a minimal example `mcp.json` client configuration that targets a local SQLTexter instance exposing the MCP HTTP surface at `/mcp`.

```json
{
   "servers": {
      "sqltexter": {
         "type": "http",
         "url": "http://127.0.0.1:5000/mcp"
      }
   },
   "inputs": []
}
```

## REST API 

### API Documentation

Swagger UI: http://localhost:5000/docs

OpenAPI JSON: http://localhost:5000/openapi.json

### Overview

SQLTexter exposes a small REST API for managing graphs (database schemas) and running Text2SQL queries. There is no authentication: every request runs as one implicit local user, so graphs are namespaced to that user.

Core endpoints
- GET /graphs — list available graphs
- GET /graphs/{graph_id}/data — return nodes/links (tables, columns, foreign keys) for the graph
- POST /graphs — upload or create a graph (JSON payload or file upload)
- POST /graphs/{graph_id} — run a Text2SQL chat query against the named graph (streaming response)

#### No authentication, but CSRF protection

There are no tokens, logins or sessions. `POST`, `PUT` and `DELETE` requests still
need the double-submit CSRF pair, which stops other websites from driving a local
server through your browser. For a script, fetch the cookie with any `GET`, then
echo it back in the `X-CSRF-Token` header:

```bash
curl -s -c jar.txt http://localhost:5000/version > /dev/null
CSRF=$(awk '$6=="csrf_token"{print $7}' jar.txt)
# then, for any POST/PUT/DELETE:
#   curl -b jar.txt -H "X-CSRF-Token: $CSRF" ...
```

`GET` requests need nothing extra.

Examples

1) List graphs (GET)

curl example:

```bash
curl -s http://localhost:5000/graphs
```

Python example:

```python
import requests
resp = requests.get('http://localhost:5000/graphs')
print(resp.json())
```

2) Get graph schema (GET)

curl example:

```bash
curl -s http://localhost:5000/graphs/my_database/data
```

Python example:

```python
resp = requests.get('http://localhost:5000/graphs/my_database/data')
print(resp.json())
```

3) Load a graph (POST) — JSON payload

```bash
curl -b jar.txt -H "X-CSRF-Token: $CSRF" -H "Content-Type: application/json" \
   -d '{"database": "my_database", "tables": [...]}' \
   http://localhost:5000/graphs
```

Or upload a file (multipart/form-data):

```bash
curl -b jar.txt -H "X-CSRF-Token: $CSRF" -F "file=@schema.json" \
   http://localhost:5000/graphs
```

4) Query a graph (POST) — run a chat-based Text2SQL request

The `POST /graphs/{graph_id}` endpoint accepts a JSON body with at least a `chat` field (an array of messages). The endpoint streams processing steps and the final SQL back as server-sent-message chunks delimited by a special boundary used by the frontend. For simple scripting you can call it and read the final JSON object from the streamed messages.

Example payload:

```json
{
   "chat": ["How many users signed up last month?"],
   "result": [],
   "instructions": "Prefer PostgreSQL compatible SQL"
}
```

curl example (simple, collects whole response):

```bash
curl -s -b jar.txt -H "X-CSRF-Token: $CSRF" -H "Content-Type: application/json" \
   -d '{"chat": ["Count orders last week"]}' \
   http://localhost:5000/graphs/my_database
```

Python example (stream-aware):

```python
import requests
import json

base = 'http://localhost:5000'
session = requests.Session()
session.get(f'{base}/version')  # sets the csrf_token cookie
headers = {'X-CSRF-Token': session.cookies['csrf_token']}
with session.post(f'{base}/graphs/my_database', headers=headers, json={"chat": ["Count orders last week"]}, stream=True) as r:
      # The server yields JSON objects delimited by a message boundary string
      boundary = '|||FALKORDB_MESSAGE_BOUNDARY|||'
      buffer = ''
      for chunk in r.iter_content(decode_unicode=True, chunk_size=1024):
            buffer += chunk
            while boundary in buffer:
                  part, buffer = buffer.split(boundary, 1)
                  if not part.strip():
                        continue
                  obj = json.loads(part)
                  print('STREAM:', obj)
```

Notes & tips
- Graph IDs are namespaced per-user. When calling the API directly use the plain graph id (the server namespaces it for the local user). For uploaded files the `database` field determines the saved graph id.
- The streaming response includes intermediate reasoning steps, follow-up questions (if the query is ambiguous or off-topic), and the final SQL. The frontend expects the boundary string `|||FALKORDB_MESSAGE_BOUNDARY|||` between messages.
- For destructive SQL (INSERT/UPDATE/DELETE etc) the service will include a confirmation step in the stream; the frontend handles this flow. If you automate destructive operations, ensure you handle confirmation properly (see the `ConfirmRequest` model in the code).

## Python SDK

The SQLTexter Python SDK allows you to use Text2SQL functionality directly in your Python applications **without running a web server**.

### Installation

```bash
# From a checkout of this repo.
# SDK only (minimal dependencies)
pip install .

# With server dependencies (FastAPI, etc.)
pip install ".[server]"

# Development (includes testing tools)
pip install ".[dev]"
```

### Quick Start

```python
import asyncio
from sqltexter import SQLTexter

async def main():
    # Initialize with FalkorDB connection
    client = SQLTexter(falkordb_url="redis://localhost:6379")

    # Connect a PostgreSQL or MySQL database
    conn = await client.connect_database("postgresql://user:pass@host:5432/mydb")
    print(f"Connected: {conn.database_id}")  # "mydb"

    # Convert natural language to SQL and execute — pass the database_id
    # returned by connect_database (un-prefixed; namespacing is internal).
    result = await client.query(conn.database_id, "Show me all customers from NYC")
    print(result.sql_query)    # SELECT * FROM customers WHERE city = 'NYC'
    print(result.results)       # [{"id": 1, "name": "Alice", "city": "NYC"}, ...]
    print(result.ai_response)   # "Found 42 customers from NYC..."

    await client.close()

asyncio.run(main())
```

### Context Manager

```python
async with SQLTexter(falkordb_url="redis://localhost:6379") as client:
    conn = await client.connect_database("postgresql://user:pass@host/mydb")
    result = await client.query(conn.database_id, "Count orders by status")
# close() runs automatically, awaiting any in-flight background memory writes.
```

### Multiple Instances

Multiple `SQLTexter` instances can run side-by-side in the same process.
Each holds its own FalkorDB connection and passes it explicitly through
every call, so there is no shared global state to collide over.

```python
async with SQLTexter(falkordb_url="redis://host-a:6379", user_id="tenant_a") as a, \
           SQLTexter(falkordb_url="redis://host-b:6379", user_id="tenant_b") as b:
    sales = await a.connect_database("postgresql://user:pass@host-a/sales")
    ops = await b.connect_database("postgresql://user:pass@host-b/ops")
    await a.query(sales.database_id, "Show top customers")
    await b.query(ops.database_id, "Count open tickets")
```

### Available Methods

| Method | Description |
|--------|-------------|
| `connect_database(db_url)` | Connect PostgreSQL/MySQL and load schema |
| `query(database, question)` | Convert natural language to SQL and execute |
| `get_schema(database)` | Retrieve database schema (tables and relationships) |
| `list_databases()` | List all connected databases |
| `delete_database(database)` | Remove database from FalkorDB |
| `refresh_schema(database)` | Re-sync schema after database changes |
| `execute_confirmed(database, sql)` | Execute confirmed destructive operations |

### Advanced Query Options

For multi-turn conversations, custom instructions, or per-request LLM overrides:

```python
from sqltexter import SQLTexter, QueryRequest

request = QueryRequest(
    question="Show their recent orders",
    chat_history=["Show all customers from NYC"],
    result_history=["Found 42 customers..."],
    instructions="Use created_at for date filtering",
    # Optional per-request LLM overrides — bypass env-based config
    custom_api_key="sk-...",
    custom_model="openai/gpt-4.1",
)

result = await client.query("mydb", request)
```

### Handling Destructive Operations

INSERT, UPDATE, DELETE operations require confirmation:

```python
result = await client.query("mydb", "Delete inactive users")

if result.requires_confirmation:
    print(f"Destructive SQL: {result.sql_query}")
    # Execute after user confirms
    confirmed = await client.execute_confirmed("mydb", result.sql_query)
```

### Requirements

- Python 3.12+
- FalkorDB instance (local or remote)
- OpenAI or Azure OpenAI API key (for LLM)
- Target SQL database (PostgreSQL or MySQL)

## Development

Follow these steps to run and develop SQLTexter from source.

### Prerequisites

- Python 3.12+
- uv (Python package manager)
- A FalkorDB instance (local or remote)
- Node.js and npm (for the React frontend)

### Install and configure

Quickstart (recommended for development):

```bash
# Clone the repo
git clone https://github.com/karthikkatu/Text2Sql.git
cd Text2Sql

# Install dependencies (backend + frontend) and start the dev server
make install
make run-dev
```

If you prefer to set up manually or need a custom environment, use uv:

```bash
# Install Python (backend) and frontend dependencies
uv sync --all-extras

# Create a local environment file
cp .env.example .env
# Edit .env with your values
```

### Run the app locally

```bash
uv run uvicorn api.index:app --host 0.0.0.0 --port 5000 --reload
```

The server will be available at http://localhost:5000

Alternatively, the repository provides Make targets for running the app:

```bash
make run-dev   # development server (reload, debug-friendly)
make run-prod  # production mode (ensure frontend build if needed)
```

### Frontend build (when needed)

The frontend is a modern React + Vite app in `app/`. Build before production runs or after frontend changes:

```bash
make install       # installs backend and frontend deps
make build-prod    # builds the frontend into app/dist/

# or manually
cd app
npm ci
npm run build
```

### AI/LLM configuration

SQLTexter supports multiple AI providers. Set one API key and SQLTexter auto-detects which provider to use.

**Priority order:** Ollama > OpenAI > Gemini > Anthropic > Cohere > Azure (default)

| Provider | API Key | Default Models |
|----------|---------|----------------|
| Ollama | `OLLAMA_MODEL` | `ollama/<your-model>`, `ollama/nomic-embed-text` |
| OpenAI | `OPENAI_API_KEY` | `openai/gpt-4.1`, `openai/text-embedding-ada-002` |
| Google Gemini | `GEMINI_API_KEY` | `gemini/gemini-3-pro-preview`, `gemini/gemini-embedding-001` |
| Anthropic | `ANTHROPIC_API_KEY` | `anthropic/claude-sonnet-4-5-20250929`, `voyage/voyage-3`* |
| Cohere | `COHERE_API_KEY` | `cohere/command-a-03-2025`, `cohere/embed-v4.0` |
| Azure OpenAI | `AZURE_API_KEY` | `azure/gpt-4.1`, `azure/text-embedding-ada-002` |

\* Anthropic has no native embeddings. You must set `VOYAGE_API_KEY` or `EMBEDDING_MODEL` for embeddings, otherwise startup will fail with an error.

**Optional: Override default models**

```bash
COMPLETION_MODEL=gemini/gemini-3-pro-preview
EMBEDDING_MODEL=gemini/gemini-embedding-001
```

Both must match your API key's provider.

#### Docker examples with AI configuration

Using OpenAI:
```bash
docker run -p 5000:5000 -it \
  -e OPENAI_API_KEY=your_openai_api_key \
  sqltexter
```

Using Google Gemini:
```bash
docker run -p 5000:5000 -it \
  -e GEMINI_API_KEY=your_gemini_api_key \
  sqltexter
```

Using Anthropic:
```bash
docker run -p 5000:5000 -it \
  -e ANTHROPIC_API_KEY=your_anthropic_api_key \
  sqltexter
```

Using Azure OpenAI:
```bash
docker run -p 5000:5000 -it \
  -e AZURE_API_KEY=your_azure_api_key \
  -e AZURE_API_BASE=https://your-resource.openai.azure.com/ \
  -e AZURE_API_VERSION=2025-03-01-preview \
  sqltexter
```

## Testing

> Quick note: many tests require FalkorDB to be available. Use the included helper to run a test DB in Docker if needed.

### Prerequisites

- Install dev dependencies: `uv sync --all-extras`
- Start FalkorDB (see `make docker-falkordb`)
- Install Playwright browsers: `uv run playwright install`

### Quick commands

Recommended: prepare the development/test environment using the Make helper (installs dependencies and Playwright browsers):

```bash
# Prepare development/test environment (installs deps and Playwright browsers)
make setup-dev
```

Alternatively, you can run the E2E-specific setup script and then run tests manually:

```bash
# Prepare E2E test environment (installs browsers and other setup)
./setup_e2e_tests.sh

# Run all tests
make test

# Run unit tests only (faster)
make test-unit

# Run E2E tests (headless)
make test-e2e

# Run E2E tests with a visible browser for debugging
make test-e2e-headed
```

### Test types

- Unit tests: focus on individual modules and utilities. Run with `make test-unit` or `uv run python -m pytest tests/ -k "not e2e"`.
- End-to-end (E2E) tests: run via Playwright and exercise UI flows, file uploads, schema processing, chat queries, and API endpoints. Use `make test-e2e`.

See `tests/e2e/README.md` for full E2E test instructions.

### CI/CD

GitHub Actions run unit and E2E tests on pushes and pull requests. Failures capture screenshots and artifacts for debugging.

## Troubleshooting

- FalkorDB connection issues: start the DB helper `make docker-falkordb` or check network/host settings.
- Playwright/browser failures: install browsers with `uv run playwright install` and ensure system deps are present.
- Missing environment variables: copy `.env.example` and fill required values.

## Project layout (high level)

- `api/` – FastAPI backend
- `app/` – React + Vite frontend
- `tests/` – unit and E2E tests



