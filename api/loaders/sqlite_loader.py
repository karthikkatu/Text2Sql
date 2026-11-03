"""SQLite loader for loading database schemas into FalkorDB graphs.

Uses Python's built-in ``sqlite3`` module, so no external database server is
needed. Connection URLs look like ``sqlite:///path/to/file.sqlite``; relative
paths resolve against ``Config.SQLITE_DATA_DIR``, and the resolved file must
live inside that directory so a URL cannot be used to read arbitrary files off
the host. Databases are always opened read-only.
"""

import contextlib
import logging
import re
import sqlite3
import time
from pathlib import Path
from typing import AsyncGenerator, Dict, Any, List, Tuple
from urllib.parse import unquote

import tqdm

from api.config import Config
from api.loaders.base_loader import BaseLoader
from api.loaders.graph_loader import load_to_graph
from api.loaders.introspection import run_introspection


class SQLiteQueryError(Exception):
    """Exception raised for SQLite query execution errors."""


def _quote(identifier: str) -> str:
    """Quote an identifier for use in a PRAGMA or statement."""
    return '"' + identifier.replace('"', '""') + '"'


def _decode_text(raw: bytes) -> str:
    """Decode TEXT leniently: some datasets (Spider) hold non-UTF-8 bytes."""
    return raw.decode("utf-8", errors="replace")


class SQLiteLoader(BaseLoader):
    """
    Loader for SQLite databases that connects and extracts schema information.
    """

    # DDL operations that modify database schema  # pylint: disable=duplicate-code
    SCHEMA_MODIFYING_OPERATIONS = {
        'CREATE', 'ALTER', 'DROP', 'RENAME', 'TRUNCATE'
    }

    @staticmethod
    def _resolve_path(connection_url: str) -> Path:
        """
        Turn a ``sqlite://`` URL into a validated path to an existing file.

        Args:
            connection_url: ``sqlite:///relative/or/absolute/path.sqlite``

        Raises:
            ValueError: if the URL is malformed, the file is missing, or the
                resolved path falls outside ``Config.SQLITE_DATA_DIR``.
        """
        if not connection_url.lower().startswith("sqlite://"):
            raise ValueError(
                "Invalid SQLite URL format. Expected sqlite:///path/to/database.sqlite"
            )

        raw = unquote(connection_url[len("sqlite://"):].split("?", 1)[0])
        # ``sqlite:///x.db`` is relative, ``sqlite:////abs/x.db`` is absolute
        # (the SQLAlchemy convention): one slash separates the empty host.
        raw = raw[1:] if raw.startswith("/") else raw
        if not raw.strip():
            raise ValueError("SQLite URL must include a database file path")

        base = Path(Config.SQLITE_DATA_DIR).resolve()
        candidate = Path(raw)
        path = (candidate if candidate.is_absolute() else base / candidate).resolve()

        if base != path and base not in path.parents:
            raise ValueError("SQLite database must be inside the configured data directory")
        if not path.is_file():
            raise ValueError("SQLite database file not found")
        return path

    @staticmethod
    def _connect(path: Path, timeout: float) -> sqlite3.Connection:
        """Open *path* read-only. The caller owns closing it."""
        conn = sqlite3.connect(
            f"{path.as_uri()}?mode=ro", uri=True, timeout=timeout, check_same_thread=False
        )
        conn.text_factory = _decode_text
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _execute_sample_query(
        cursor, table_name: str, col_name: str, sample_size: int = 3
    ) -> List[Any]:
        """
        Execute query to get random sample values for a column.
        SQLite implementation using ORDER BY RANDOM() for random sampling.
        """
        query = (
            f"SELECT DISTINCT {_quote(col_name)} AS v FROM {_quote(table_name)} "
            f"WHERE {_quote(col_name)} IS NOT NULL ORDER BY RANDOM() LIMIT ?"
        )
        cursor.execute(query, (sample_size,))
        return [row["v"] for row in cursor.fetchall() if row["v"] is not None]

    @staticmethod
    def _serialize_value(value):
        """Convert BLOBs (the one SQLite type that is not JSON serializable) to hex."""
        if isinstance(value, (bytes, bytearray, memoryview)):
            return bytes(value).hex()
        return value

    @staticmethod
    def _introspect_schema(path: Path, db_name: str):
        """Connect, introspect and close — all inside one worker thread."""
        conn = None
        try:
            conn = SQLiteLoader._connect(path, Config.DB_CONNECT_TIMEOUT)
            cursor = conn.cursor()
            entities = SQLiteLoader.extract_tables_info(cursor, db_name)
            relationships = SQLiteLoader.extract_relationships(entities)
            return entities, relationships
        finally:
            if conn is not None:
                conn.close()

    @staticmethod
    async def load(  # pylint: disable=arguments-differ
        prefix: str,
        connection_url: str,
        db=None,
    ) -> AsyncGenerator[tuple[bool, str], None]:
        """
        Load the graph data from a SQLite database into the graph database.

        Args:
            prefix: Graph name prefix (the user id).
            connection_url: ``sqlite:///path/to/database.sqlite``
            db: Optional FalkorDB handle; falls back to the server singleton.
        """
        try:
            path = SQLiteLoader._resolve_path(connection_url)
            db_name = path.stem

            yield True, "Extracting table information..."
            entities, relationships = await run_introspection(
                SQLiteLoader._introspect_schema, path, db_name
            )

            yield True, "Loading data into graph..."
            await load_to_graph(f"{prefix}_{db_name}", entities, relationships,
                                db_name=db_name, db_url=connection_url, db=db)

            yield True, (f"SQLite schema loaded successfully. "
                         f"Found {len(entities)} tables.")

        except ValueError as e:
            logging.error("Invalid SQLite connection URL: %s", e)
            yield False, "Invalid SQLite database path"
        except sqlite3.Error as e:
            logging.error("SQLite connection error: %s", e)
            yield False, "Failed to open SQLite database"
        except Exception as e:  # pylint: disable=broad-exception-caught
            logging.error("Error loading SQLite schema: %s", e)
            yield False, "Failed to load SQLite database schema"

    @staticmethod
    def extract_tables_info(cursor, db_name: str) -> Dict[str, Any]:  # pylint: disable=unused-argument
        """
        Extract table and column information from a SQLite database.

        Returns:
            Dict containing table information, in the shape ``load_to_graph`` expects.
        """
        entities = {}

        cursor.execute(
            "SELECT name FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )
        table_names = [row["name"] for row in cursor.fetchall()]

        for table_name in tqdm.tqdm(table_names, desc="Extracting table information"):
            foreign_keys = SQLiteLoader.extract_foreign_keys(cursor, table_name)
            columns_info = SQLiteLoader.extract_columns_info(
                cursor, table_name, {fk["column"] for fk in foreign_keys}
            )
            entities[table_name] = {
                'description': f"Table: {table_name}",
                'columns': columns_info,
                'foreign_keys': foreign_keys,
                'col_descriptions': [c['description'] for c in columns_info.values()],
            }

        # A FOREIGN KEY without a column list references the parent's primary
        # key; PRAGMA reports that target as NULL, so fill it in here.
        for table_info in entities.values():
            for fk in table_info['foreign_keys']:
                if fk['referenced_column'] is None:
                    parent = entities.get(fk['referenced_table'], {}).get('columns', {})
                    pks = [n for n, c in parent.items() if c['key'] == 'PRIMARY KEY']
                    fk['referenced_column'] = pks[0] if len(pks) == 1 else None
            table_info['foreign_keys'] = [
                fk for fk in table_info['foreign_keys'] if fk['referenced_column'] is not None
            ]

        return entities

    @staticmethod
    def extract_columns_info(
        cursor, table_name: str, fk_columns: set | None = None
    ) -> Dict[str, Any]:
        """Extract column information for a specific table."""
        fk_columns = fk_columns or set()
        cursor.execute(f"PRAGMA table_info({_quote(table_name)})")
        columns = cursor.fetchall()
        columns_info = {}

        for col in columns:
            col_name = col["name"]
            data_type = (col["type"] or "").lower() or "unknown"
            is_nullable = 'NO' if col["notnull"] or col["pk"] else 'YES'
            column_default = col["dflt_value"]

            if col["pk"]:
                key_type = 'PRIMARY KEY'
            elif col_name in fk_columns:
                key_type = 'FOREIGN KEY'
            else:
                key_type = 'NONE'

            description_parts = [f"Column {col_name} of type {data_type}"]
            if key_type != 'NONE':
                description_parts.append(f"({key_type})")
            if is_nullable == 'NO':
                description_parts.append("(NOT NULL)")
            if column_default is not None:
                description_parts.append(f"(Default: {column_default})")

            sample_values = SQLiteLoader.extract_sample_values_for_column(
                cursor, table_name, col_name
            )

            columns_info[col_name] = {
                'type': data_type,
                'null': is_nullable,
                'key': key_type,
                'description': ' '.join(description_parts),
                'default': column_default,
                'sample_values': sample_values,
            }

        return columns_info

    @staticmethod
    def extract_foreign_keys(cursor, table_name: str) -> List[Dict[str, Any]]:
        """Extract foreign key information for a specific table."""
        cursor.execute(f"PRAGMA foreign_key_list({_quote(table_name)})")
        return [
            {
                # SQLite does not name FK constraints; (table, id) is unique and
                # keeps the columns of a composite key together.
                'constraint_name': f"fk_{table_name}_{fk['id']}",
                'column': fk["from"],
                'referenced_table': fk["table"],
                'referenced_column': fk["to"],
            }
            for fk in cursor.fetchall()
        ]

    @staticmethod
    def extract_relationships(entities: Dict[str, Any]) -> Dict[str, List[Dict[str, str]]]:
        """Build the relationship map from the foreign keys already extracted."""
        relationships: Dict[str, List[Dict[str, str]]] = {}
        for table_name, table_info in entities.items():
            for fk in table_info['foreign_keys']:
                relationships.setdefault(fk['constraint_name'], []).append({
                    'from': table_name,
                    'to': fk['referenced_table'],
                    'source_column': fk['column'],
                    'target_column': fk['referenced_column'],
                    'note': f"Foreign key constraint: {fk['constraint_name']}",
                })
        return relationships

    @staticmethod
    def is_schema_modifying_query(sql_query: str) -> Tuple[bool, str]:
        """
        Check if a SQL query modifies the database schema.

        Returns:
            Tuple of (is_schema_modifying, operation_type)
        """
        if not sql_query or not sql_query.strip():
            return False, ""

        first_word = re.split(r"\s+", sql_query.strip().upper(), maxsplit=1)[0]
        if first_word in SQLiteLoader.SCHEMA_MODIFYING_OPERATIONS:
            return True, first_word
        return False, ""

    @staticmethod
    async def refresh_graph_schema(graph_id: str, db_url: str, db=None) -> Tuple[bool, str]:
        """
        Refresh the graph schema by clearing existing data and reloading from the database.

        Returns:
            Tuple of (success, message)
        """
        try:
            logging.info("Schema modification detected. Refreshing graph schema.")

            from api.core.db_resolver import resolve_db  # pylint: disable=import-outside-toplevel

            graph = resolve_db(db).select_graph(graph_id)
            await graph.delete()

            # graph_id is "<prefix>_<database_name>"; the load below rebuilds it.
            parts = graph_id.split('_')
            prefix = '_'.join(parts[:-1]) if len(parts) >= 2 else graph_id

            success, message = False, ""
            async for success, message in SQLiteLoader.load(prefix, db_url, db=db):
                if not success:
                    break

            if success:
                logging.info("Graph schema refreshed successfully.")
                return True, message

            logging.error("Schema refresh failed")
            return False, "Failed to reload schema"

        except Exception as e:  # pylint: disable=broad-exception-caught
            logging.error("Error refreshing graph schema: %s", str(e))
            return False, "Error refreshing graph schema"

    @staticmethod
    def execute_sql_query(sql_query: str, db_url: str) -> List[Dict[str, Any]]:
        """
        Execute a SQL query on the SQLite database and return the results.

        The database is opened read-only, so anything that writes fails with a
        ``SQLiteQueryError``. ``Config.DB_STATEMENT_TIMEOUT`` bounds the run
        time via a progress handler, since SQLite has no server-side timeout.
        """
        conn = None
        try:
            path = SQLiteLoader._resolve_path(db_url)
            conn = SQLiteLoader._connect(path, Config.DB_CONNECT_TIMEOUT)

            deadline = time.monotonic() + Config.DB_STATEMENT_TIMEOUT
            # Called every N VM instructions; a truthy return aborts the statement.
            conn.set_progress_handler(lambda: time.monotonic() > deadline, 10_000)

            cursor = conn.cursor()
            cursor.execute(sql_query)

            if cursor.description is not None:
                return [
                    {key: SQLiteLoader._serialize_value(row[key]) for key in row.keys()}
                    for row in cursor.fetchall()
                ]

            sql_type = sql_query.strip().split()[0].upper()
            if sql_type in ['INSERT', 'UPDATE', 'DELETE']:
                return [{
                    "operation": sql_type,
                    "affected_rows": cursor.rowcount,
                    "status": "success",
                }]
            return [{"operation": sql_type, "status": "success"}]

        except (sqlite3.Error, ValueError) as e:
            logging.error("SQLite query execution error: %s", e)
            raise SQLiteQueryError(f"SQLite query execution error: {str(e)}") from e
        except Exception as e:
            logging.error("Error executing SQL query: %s", e)
            raise SQLiteQueryError(f"Error executing SQL query: {str(e)}") from e
        finally:
            if conn is not None:
                with contextlib.suppress(Exception):
                    conn.close()
