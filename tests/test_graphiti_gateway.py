"""Tests that Graphiti's OpenAI clients honour a configured gateway.

The rest of the app reaches the LLM through litellm, which reads OPENAI_API_BASE.
The OpenAI SDK behind Graphiti does not, so an unconfigured client sends the
gateway's key to api.openai.com.
"""

from unittest.mock import MagicMock

import pytest

from api.memory import graphiti_tool
from graphiti_core.llm_client.openai_generic_client import OpenAIGenericClient


GATEWAY = "https://gateway.example.com/v1"


@pytest.fixture(name="graphiti_kwargs")
def graphiti_kwargs_fixture(monkeypatch):
    """Build the client against a fake Graphiti and return what it was given."""
    fake_graphiti = MagicMock()
    monkeypatch.setattr(graphiti_tool, "Graphiti", fake_graphiti)
    monkeypatch.setattr(graphiti_tool.Config, "AZURE_FLAG", False)
    monkeypatch.setattr(graphiti_tool.Config, "LLM_PROVIDER", "openai")
    monkeypatch.setattr(graphiti_tool.Config, "COMPLETION_MODEL", "openai/gateway-llm")
    monkeypatch.setattr(graphiti_tool.Config, "EMBEDDING_MODEL_NAME", "openai/gateway-embed")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_API_BASE", raising=False)

    def build() -> dict:
        graphiti_tool.create_graphiti_client(MagicMock())
        return fake_graphiti.call_args.kwargs

    return build


@pytest.mark.parametrize("variable", ["OPENAI_API_BASE", "OPENAI_BASE_URL"])
def test_gateway_reaches_every_client(graphiti_kwargs, monkeypatch, variable):
    monkeypatch.setenv(variable, GATEWAY)

    kwargs = graphiti_kwargs()

    for name in ("llm_client", "embedder", "cross_encoder"):
        assert str(kwargs[name].client.base_url).rstrip("/") == GATEWAY, name


def test_gateway_uses_configured_models(graphiti_kwargs, monkeypatch):
    monkeypatch.setenv("OPENAI_API_BASE", GATEWAY)

    kwargs = graphiti_kwargs()

    assert isinstance(kwargs["llm_client"], OpenAIGenericClient)
    assert kwargs["llm_client"].model == "gateway-llm"
    assert kwargs["llm_client"].small_model == "gateway-llm"
    assert kwargs["cross_encoder"].config.model == "gateway-llm"
    assert kwargs["embedder"].config.embedding_model == "gateway-embed"


def test_without_gateway_graphiti_keeps_its_defaults(graphiti_kwargs):
    kwargs = graphiti_kwargs()

    assert "llm_client" not in kwargs
    assert "cross_encoder" not in kwargs
    assert "api.openai.com" in str(kwargs["embedder"].client.base_url)
