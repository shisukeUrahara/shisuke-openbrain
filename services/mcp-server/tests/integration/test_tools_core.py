"""Integration tests for the four core MCP tools.

Tools are invoked directly as Python coroutines via FastMCP's
`get_tool` lookup so we can exercise their full DB+embed paths
without standing up the HTTP transport. The embed provider is
patched at the wire (httpx) layer to return a deterministic vector
for any input — that way embedding-driven similarity assertions are
reproducible.

Layer: integration
Phase: 02
Run:   pytest services/mcp-server/tests/integration/test_tools_core.py -v
"""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio
from fastmcp import FastMCP

from brain_mcp import db
from brain_mcp.tools import core_browse, core_capture, core_search, core_stats


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

def _stub_openrouter(monkeypatch: pytest.MonkeyPatch, vector: list[float]) -> None:
    """Stub OpenRouter to return the given vector for any input."""
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"data": [{"embedding": vector}]})
    )
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: real_client(transport=transport, **kw),
    )


async def _call_tool(mcp: FastMCP, name: str, args: dict):
    """Call a registered FunctionTool by name and return its raw result."""
    tool = await mcp.get_tool(name)
    return await tool.fn(**args)


@pytest_asyncio.fixture
async def mcp_with_tools(config, pool):
    """A FastMCP instance with the four core tools registered, plus a
    valid OPENROUTER_API_KEY in the config so capture/search succeed."""
    # Override the no-key config with one carrying a stub key.
    from dataclasses import replace

    config_with_key = replace(config, openrouter_api_key="sk-or-test")
    mcp = FastMCP(name="test-server")
    core_capture.register(mcp, config=config_with_key)
    core_search.register(mcp, config=config_with_key)
    core_browse.register(mcp, config=config_with_key)
    core_stats.register(mcp, config=config_with_key)
    return mcp


# ──────────────────────────────────────────────────────────────────
# capture
# ──────────────────────────────────────────────────────────────────

async def test_capture_inserts_and_embeds(clean_pg, mcp_with_tools, monkeypatch):
    _stub_openrouter(monkeypatch, [0.1] * 1536)

    result = await _call_tool(
        mcp_with_tools,
        "capture",
        {"content": "first capture via mcp tool"},
    )
    assert "id" in result
    assert len(result["fingerprint"]) == 64
    assert result["embedded"] is True

    async with db.conn() as connection:
        row = await connection.fetchrow(
            "SELECT content, embedding IS NOT NULL AS has_embedding "
            "FROM thoughts WHERE id = $1",
            result["id"],
        )
    assert row["content"] == "first capture via mcp tool"
    assert row["has_embedding"] is True


async def test_capture_is_idempotent(clean_pg, mcp_with_tools, monkeypatch):
    """Capturing the same content twice returns the same id and yields
    only one row in the table."""
    _stub_openrouter(monkeypatch, [0.2] * 1536)

    first = await _call_tool(mcp_with_tools, "capture", {"content": "idempotent body"})
    second = await _call_tool(mcp_with_tools, "capture", {"content": "idempotent body"})
    assert first["id"] == second["id"]

    async with db.conn() as connection:
        n = await connection.fetchval(
            "SELECT count(*) FROM thoughts WHERE content = 'idempotent body'"
        )
    assert n == 1


async def test_capture_rejects_empty_content(clean_pg, mcp_with_tools):
    with pytest.raises(ValueError, match="non-empty"):
        await _call_tool(mcp_with_tools, "capture", {"content": "   "})


# ──────────────────────────────────────────────────────────────────
# search
# ──────────────────────────────────────────────────────────────────

async def test_search_finds_captured_thought(clean_pg, mcp_with_tools, monkeypatch):
    """Capture a thought and immediately search by the same content;
    the captured row should come back first."""
    _stub_openrouter(monkeypatch, [0.3] * 1536)

    captured = await _call_tool(
        mcp_with_tools, "capture",
        {"content": "search target alpha"},
    )
    results = await _call_tool(
        mcp_with_tools, "search",
        {"query": "search target alpha", "match_count": 3},
    )
    assert any(r["id"] == captured["id"] for r in results)
    assert results[0]["similarity"] == pytest.approx(1.0, abs=1e-6)


async def test_search_respects_metadata_filter(clean_pg, mcp_with_tools, monkeypatch):
    """metadata_filter narrows results to rows whose metadata contains
    the supplied object."""
    _stub_openrouter(monkeypatch, [0.4] * 1536)

    await _call_tool(
        mcp_with_tools, "capture",
        {"content": "filtered project alpha", "metadata": {"project": "ax"}},
    )
    await _call_tool(
        mcp_with_tools, "capture",
        {"content": "filtered project beta", "metadata": {"project": "other"}},
    )

    matches = await _call_tool(
        mcp_with_tools, "search",
        {"query": "filtered project", "metadata_filter": {"project": "ax"}},
    )
    contents = {r["content"] for r in matches}
    assert "filtered project alpha" in contents
    assert "filtered project beta" not in contents


async def test_search_validates_arguments(clean_pg, mcp_with_tools):
    with pytest.raises(ValueError, match="non-empty"):
        await _call_tool(mcp_with_tools, "search", {"query": ""})
    with pytest.raises(ValueError, match="match_count"):
        await _call_tool(mcp_with_tools, "search", {"query": "x", "match_count": 0})
    with pytest.raises(ValueError, match="match_threshold"):
        await _call_tool(
            mcp_with_tools, "search",
            {"query": "x", "match_threshold": 1.5},
        )


# ──────────────────────────────────────────────────────────────────
# browse
# ──────────────────────────────────────────────────────────────────

async def test_browse_returns_recent_thoughts_newest_first(
    clean_pg, mcp_with_tools, monkeypatch
):
    _stub_openrouter(monkeypatch, [0.5] * 1536)

    await _call_tool(mcp_with_tools, "capture", {"content": "browse one"})
    await _call_tool(mcp_with_tools, "capture", {"content": "browse two"})
    await _call_tool(mcp_with_tools, "capture", {"content": "browse three"})

    results = await _call_tool(mcp_with_tools, "browse", {"limit": 10})
    contents = [r["content"] for r in results]
    # newest first
    assert contents[:3] == ["browse three", "browse two", "browse one"]


async def test_browse_respects_limit(clean_pg, mcp_with_tools, monkeypatch):
    _stub_openrouter(monkeypatch, [0.6] * 1536)
    for i in range(5):
        await _call_tool(mcp_with_tools, "capture", {"content": f"limit {i}"})
    results = await _call_tool(mcp_with_tools, "browse", {"limit": 2})
    assert len(results) == 2


async def test_browse_validates_arguments(clean_pg, mcp_with_tools):
    with pytest.raises(ValueError, match="limit"):
        await _call_tool(mcp_with_tools, "browse", {"limit": 0})
    with pytest.raises(ValueError, match="since_days"):
        await _call_tool(mcp_with_tools, "browse", {"since_days": -1})


# ──────────────────────────────────────────────────────────────────
# stats
# ──────────────────────────────────────────────────────────────────

async def test_stats_counts_thoughts(clean_pg, mcp_with_tools, monkeypatch):
    _stub_openrouter(monkeypatch, [0.7] * 1536)

    initial = await _call_tool(mcp_with_tools, "stats", {})
    assert initial["total_thoughts"] == 0

    await _call_tool(mcp_with_tools, "capture", {"content": "stats one"})
    await _call_tool(mcp_with_tools, "capture", {"content": "stats two"})

    after = await _call_tool(mcp_with_tools, "stats", {})
    assert after["total_thoughts"] == 2
    assert after["embedded_thoughts"] == 2
    assert after["rate_last_7d"] == 2


async def test_stats_aggregates_topics(clean_pg, mcp_with_tools, monkeypatch):
    _stub_openrouter(monkeypatch, [0.8] * 1536)
    await _call_tool(
        mcp_with_tools, "capture",
        {"content": "topic A1", "metadata": {"topics": ["alpha"]}},
    )
    await _call_tool(
        mcp_with_tools, "capture",
        {"content": "topic A2", "metadata": {"topics": ["alpha", "beta"]}},
    )
    await _call_tool(
        mcp_with_tools, "capture",
        {"content": "topic B", "metadata": {"topics": ["beta"]}},
    )
    result = await _call_tool(mcp_with_tools, "stats", {})
    top = {item["topic"]: item["count"] for item in result["top_topics"]}
    assert top.get("alpha") == 2
    assert top.get("beta") == 2
