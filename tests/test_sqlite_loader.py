"""Tests for SQLite loader functionality."""
# pylint: disable=protected-access

import sqlite3

import pytest

# Imported via api.core.pipeline first: importing a loader module directly hits
# a circular import (see test_loader_contract.py).
from api.core.pipeline import SQLiteLoader, get_database_type_and_loader, detect_destructive_operation
from api.config import Config


async def _consume_loader(loader_gen):
    """Consume an async generator loader and return every yielded message."""
    return [item async for item in loader_gen]


@pytest.fixture(name="data_dir")
def fixture_data_dir(tmp_path, monkeypatch):
    """A data directory holding one small database with a foreign key."""
    monkeypatch.setattr(Config, "SQLITE_DATA_DIR", str(tmp_path))
    conn = sqlite3.connect(tmp_path / "shop.sqlite")
    conn.executescript(
        """
        CREATE TABLE customer (id INTEGER PRIMARY KEY, name TEXT NOT NULL, blob_col BLOB);
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER REFERENCES customer,
            total REAL DEFAULT 0
        );
        INSERT INTO customer VALUES (1, 'Ada', x'ff00'), (2, 'Grace', NULL);
        INSERT INTO orders VALUES (1, 1, 9.5), (2, 1, 20), (3, 2, 5);
        """
    )
    conn.commit()
    conn.close()
    return tmp_path


URL = "sqlite:///shop.sqlite"


@pytest.mark.unit
class TestSQLiteLoader:
    """Test cases for SQLiteLoader class."""

    def test_url_is_routed_to_sqlite_loader(self):
        db_type, loader = get_database_type_and_loader(URL)
        assert db_type == "sqlite"
        assert loader is SQLiteLoader

    def test_resolve_relative_and_absolute(self, data_dir):
        expected = (data_dir / "shop.sqlite").resolve()
        assert SQLiteLoader._resolve_path(URL) == expected
        assert SQLiteLoader._resolve_path(f"sqlite:///{expected}") == expected

    @pytest.mark.parametrize("url", [
        "sqlite:///../outside.sqlite",
        "sqlite:////etc/passwd",
        "sqlite:///missing.sqlite",
        "sqlite://",
        "mysql://u:p@h/db",
    ])
    def test_resolve_rejects_bad_urls(self, data_dir, url):
        with pytest.raises(ValueError):
            SQLiteLoader._resolve_path(url)

    def test_introspection(self, data_dir):
        path = SQLiteLoader._resolve_path(URL)
        entities, relationships = SQLiteLoader._introspect_schema(path, "shop")

        assert set(entities) == {"customer", "orders"}
        customer = entities["customer"]["columns"]
        assert customer["id"]["key"] == "PRIMARY KEY"
        assert customer["name"]["null"] == "NO"
        assert sorted(customer["name"]["sample_values"]) == ["Ada", "Grace"]
        assert entities["orders"]["columns"]["customer_id"]["key"] == "FOREIGN KEY"
        assert entities["orders"]["columns"]["total"]["default"] == "0"

        # ``REFERENCES customer`` names no column; it must resolve to the parent's PK.
        assert relationships == {
            "fk_orders_0": [{
                "from": "orders", "to": "customer",
                "source_column": "customer_id", "target_column": "id",
                "note": "Foreign key constraint: fk_orders_0",
            }]
        }

    def test_execute_select(self, data_dir):
        rows = SQLiteLoader.execute_sql_query(
            "SELECT customer_id, SUM(total) AS spent FROM orders GROUP BY customer_id ORDER BY customer_id",
            URL,
        )
        assert rows == [{"customer_id": 1, "spent": 29.5}, {"customer_id": 2, "spent": 5.0}]

    def test_blob_values_are_json_safe(self, data_dir):
        rows = SQLiteLoader.execute_sql_query("SELECT blob_col FROM customer ORDER BY id", URL)
        assert rows == [{"blob_col": "ff00"}, {"blob_col": None}]

    @pytest.mark.parametrize("sql", [
        "DELETE FROM orders",
        "DROP TABLE orders",
        "INSERT INTO orders VALUES (9, 1, 1)",
    ])
    def test_database_is_read_only(self, data_dir, sql):
        with pytest.raises(Exception, match="readonly"):
            SQLiteLoader.execute_sql_query(sql, URL)
        conn = sqlite3.connect(data_dir / "shop.sqlite")
        assert conn.execute("SELECT COUNT(*) FROM orders").fetchone()[0] == 3
        conn.close()

    def test_invalid_sql_raises_query_error(self, data_dir):
        with pytest.raises(Exception, match="no such table"):
            SQLiteLoader.execute_sql_query("SELECT * FROM nope", URL)

    def test_statement_timeout_aborts_runaway_query(self, data_dir, monkeypatch):
        monkeypatch.setattr(Config, "DB_STATEMENT_TIMEOUT", 0)
        runaway = (
            "WITH RECURSIVE r(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM r) "
            "SELECT COUNT(*) FROM r"
        )
        with pytest.raises(Exception, match="interrupted"):
            SQLiteLoader.execute_sql_query(runaway, URL)

    @pytest.mark.parametrize("sql,expected", [
        ("CREATE TABLE t (a INT)", (True, "CREATE")),
        ("  drop table t", (True, "DROP")),
        ("SELECT 1", (False, "")),
        ("", (False, "")),
    ])
    def test_is_schema_modifying_query(self, sql, expected):
        assert SQLiteLoader.is_schema_modifying_query(sql) == expected

    def test_destructive_detection_uses_sqlite_dialect(self):
        assert detect_destructive_operation("SELECT * FROM t", "sqlite")[1] is False
        assert detect_destructive_operation("DELETE FROM t", "sqlite")[1] is True

    def test_load_reports_failure_for_bad_path(self, data_dir):
        import asyncio  # pylint: disable=import-outside-toplevel
        results = asyncio.run(_consume_loader(SQLiteLoader.load("user", "sqlite:///missing.sqlite")))
        assert results == [(False, "Invalid SQLite database path")]
