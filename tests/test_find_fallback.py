"""``api.graph.find`` must still search when the model's answer is unusable.

Some models answer an answerable question with empty ``tables_descriptions`` and
``columns_descriptions``. With nothing to embed, ``find`` used to return no
tables, so the analysis step saw an empty schema and refused the question as
"schema not provided". A model that describes only columns used to lose those
columns the same way.
"""

import asyncio
import json
import types

import pytest

import api.graph as graph_module

pytestmark = pytest.mark.unit

TABLE_ROW = ["car_makers", "makers", "Foreign keys: ", [{"id": "int"}]]
COLUMN_ROW = ["countries", "countries", "Foreign keys: ", [{"id": "int"}]]


@pytest.fixture(name="searches")
def _searches(monkeypatch):
    """Stub every graph search and record what ``find`` asked each one."""
    calls = {"tables": None, "columns": None, "seeds": None}

    async def find_tables(_graph, embeddings):
        calls["tables"] = embeddings
        return [list(TABLE_ROW)]

    async def find_tables_by_columns(_graph, embeddings):
        calls["columns"] = embeddings
        return [list(COLUMN_ROW)]

    async def neighbours(_graph, names):
        calls["seeds"] = names
        return []

    monkeypatch.setattr(graph_module, "_find_tables", find_tables)
    monkeypatch.setattr(graph_module, "_find_tables_by_columns", find_tables_by_columns)
    monkeypatch.setattr(graph_module, "_find_tables_sphere", neighbours)
    monkeypatch.setattr(graph_module, "_find_connecting_tables", neighbours)
    monkeypatch.setattr(graph_module, "resolve_db", lambda db: types.SimpleNamespace(
        select_graph=lambda graph_id: None))
    monkeypatch.setattr(
        graph_module.Config, "EMBEDDING_MODEL",
        types.SimpleNamespace(embed=lambda texts: [[float(i)] for i, _ in enumerate(texts)]),
    )
    return calls


def _model_says(monkeypatch, tables, columns):
    answer = json.dumps({
        "tables_descriptions": [{"name": "t", "description": d} for d in tables],
        "columns_descriptions": [{"name": "c", "description": d} for d in columns],
    })
    monkeypatch.setattr(graph_module, "run_completion", lambda *a, **k: answer)


def _find():
    return asyncio.run(graph_module.find("g", ["How many car makers per continent?"], "cars"))


def test_empty_model_answer_falls_back_to_the_question(monkeypatch, searches):
    _model_says(monkeypatch, [], [])

    names = [t[0] for t in _find()]

    assert searches["tables"] == [[0.0]] and searches["columns"] == [[1.0]]
    assert names == ["car_makers", "countries"]


def test_column_only_answer_keeps_the_column_matches(monkeypatch, searches):
    _model_says(monkeypatch, [], ["the continent a country is on"])

    names = [t[0] for t in _find()]

    assert searches["tables"] is None
    assert names == ["countries"]
    # With no table match, the column matches seed the neighbourhood searches.
    assert searches["seeds"] == ["countries"]


def test_table_answer_still_seeds_from_the_table_matches(monkeypatch, searches):
    _model_says(monkeypatch, ["car makers"], ["maker name"])

    names = sorted(t[0] for t in _find())

    assert names == ["car_makers", "countries"]
    assert searches["seeds"] == ["car_makers"]
