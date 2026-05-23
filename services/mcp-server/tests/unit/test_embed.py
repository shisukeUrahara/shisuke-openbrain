"""Unit tests for brain_mcp.embed.

Mocks at the httpx wire level — closer to the wire = fewer false
positives. Confirms request shape per provider and error surfacing.

Layer: unit
Phase: 02
Run:   pytest services/mcp-server/tests/unit/test_embed.py -v
"""
from __future__ import annotations

import json

import httpx
import pytest

from brain_mcp import embed
from brain_mcp.config import Config, Modules


def _config(provider: str = "openrouter", *, key: str | None = "sk-or-test"):
    return Config(
        database_url="postgresql://test/test",
        brain_key="a" * 64,
        embed_provider=provider,
        openrouter_api_key=key,
        ollama_url="http://ollama:11434",
        modules=Modules(),
    )


# ──────────────────────────────────────────────────────────────────
# OpenRouter branch
# ──────────────────────────────────────────────────────────────────

async def test_openrouter_request_shape(monkeypatch):
    """The OpenRouter call carries the right URL, model, headers, and body."""
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["auth"] = request.headers.get("authorization")
        captured["body"] = request.read().decode()
        return httpx.Response(
            200,
            json={"data": [{"embedding": [0.1, 0.2, 0.3]}]},
        )

    transport = httpx.MockTransport(handler)
    _real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: _real_client(transport=transport, **kw))

    vec = await embed.embed("hello world", config=_config())
    assert vec == [0.1, 0.2, 0.3]
    assert "openrouter.ai/api/v1/embeddings" in captured["url"]
    assert captured["auth"] == "Bearer sk-or-test"
    body_json = json.loads(captured["body"])
    assert body_json["model"] == "openai/text-embedding-3-small"
    assert body_json["input"] == "hello world"


async def test_openrouter_missing_key_raises():
    """Calling the OpenRouter branch without OPENROUTER_API_KEY raises
    an explicit EmbeddingError — silent failure here would lead to
    half the database with null embeddings."""
    with pytest.raises(embed.EmbeddingError, match="OPENROUTER_API_KEY"):
        await embed.embed("x", config=_config(key=None))


async def test_openrouter_non_2xx_raises_with_body(monkeypatch):
    transport = httpx.MockTransport(
        lambda req: httpx.Response(500, text="upstream broken")
    )
    _real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: _real_client(transport=transport, **kw),
    )
    with pytest.raises(embed.EmbeddingError, match="500"):
        await embed.embed("x", config=_config())


async def test_openrouter_unexpected_shape_raises(monkeypatch):
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"unexpected": "payload"})
    )
    _real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: _real_client(transport=transport, **kw),
    )
    with pytest.raises(embed.EmbeddingError, match="unexpected"):
        await embed.embed("x", config=_config())


# ──────────────────────────────────────────────────────────────────
# Ollama branch
# ──────────────────────────────────────────────────────────────────

async def test_ollama_request_shape(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = request.read().decode()
        return httpx.Response(200, json={"embedding": [0.5, 0.6]})

    transport = httpx.MockTransport(handler)
    _real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: _real_client(transport=transport, **kw),
    )

    vec = await embed.embed("hi", config=_config(provider="ollama"))
    assert vec == [0.5, 0.6]
    assert captured["url"].endswith("/api/embeddings")
    body_json = json.loads(captured["body"])
    assert body_json["model"] == "bge-m3"
    assert body_json["prompt"] == "hi"


async def test_ollama_non_2xx_raises(monkeypatch):
    transport = httpx.MockTransport(lambda req: httpx.Response(503, text="busy"))
    _real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: _real_client(transport=transport, **kw),
    )
    with pytest.raises(embed.EmbeddingError, match="503"):
        await embed.embed("x", config=_config(provider="ollama"))


# ──────────────────────────────────────────────────────────────────
# Unknown provider
# ──────────────────────────────────────────────────────────────────

async def test_unknown_provider_raises():
    cfg = _config(provider="nonsense")
    with pytest.raises(embed.EmbeddingError, match="unknown embed provider"):
        await embed.embed("x", config=cfg)
