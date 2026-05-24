"""End-to-end: capture a thought over MCP, then find it via search.

This is the highest-level test in the suite — it speaks JSON-RPC to a
*running* mcp-server (no fixtures, no mocks) exactly as an AI client
would. It proves the whole spine works: HTTP transport -> auth ->
capture -> embedding -> upsert -> match_thoughts -> search.

Because capture and search both embed text, this needs a real
embedding provider reachable by the server (OPENROUTER_API_KEY set on
the mcp-server, or a local Ollama). When that is not available the
capture call comes back as a JSON-RPC error and the test SKIPS rather
than fails — the harness stays committed and green in CI, and turns
into a real assertion the moment a key is present. Same discipline as
the workers: token is a runtime concern, not a build/test concern.

Run:
    export BRAIN_KEY=...            # from .env
    docker compose up -d            # mcp-server must be healthy
    pytest tests/e2e -v
"""
from __future__ import annotations

import os
import time
import uuid

import httpx
import pytest


BASE_URL = os.environ.get("BRAIN_URL", "http://localhost:8080")
MCP_URL = f"{BASE_URL.rstrip('/')}/mcp"
KEY = os.environ.get("BRAIN_KEY")

# JSON-RPC over the streamable-http transport: send both accept types so
# the server may answer with plain JSON or text/event-stream.
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

pytestmark = pytest.mark.e2e


def _server_reachable() -> bool:
    try:
        r = httpx.get(f"{BASE_URL.rstrip('/')}/health", timeout=2.0)
        return r.status_code == 200
    except httpx.HTTPError:
        return False


requires_server = pytest.mark.skipif(
    not KEY or not _server_reachable(),
    reason="needs BRAIN_KEY set and a running mcp-server on BRAIN_URL",
)


def _parse_sse_or_json(text: str) -> dict:
    """FastMCP may answer JSON-RPC as text/event-stream. Strip the
    leading `data: ` of the last data line if present, else parse as
    plain JSON."""
    import json

    text = text.strip()
    if text.startswith("data:") or "\ndata:" in text:
        for line in reversed(text.splitlines()):
            if line.startswith("data:"):
                return json.loads(line[len("data:") :].strip())
    return json.loads(text)


def _rpc(method: str, params: dict) -> dict:
    with httpx.Client(timeout=30.0) as client:
        r = client.post(
            MCP_URL,
            headers={**HEADERS, "x-brain-key": KEY},
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        )
        r.raise_for_status()
        body = _parse_sse_or_json(r.text)
    if "error" in body:
        raise AssertionError(f"JSON-RPC transport error: {body['error']}")
    return body["result"]


def _call_tool(name: str, arguments: dict) -> dict:
    """Returns the raw tools/call result envelope (has isError,
    content, structuredContent)."""
    return _rpc("tools/call", {"name": name, "arguments": arguments})


def _error_text(result: dict) -> str | None:
    """If the tools/call result is an error, return its text; else None."""
    if not result.get("isError"):
        return None
    for item in result.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            return item.get("text", "tool error")
    return "tool error"


@requires_server
def test_capture_then_search_finds_it():
    """Capture a uniquely-tagged thought, then search for the tag and
    assert the same content comes back — the full capture/search loop.

    Skips (does not fail) when the server has no embedding provider,
    since both capture and search depend on one."""
    tag = f"e2e-{uuid.uuid4().hex[:8]}"
    content = f"phase 3 capture loop check {tag}"

    cap = _call_tool("capture", {"content": content})
    err = _error_text(cap)
    if err and "embed" in err.lower():
        pytest.skip(f"no embedding provider on the server: {err}")
    assert err is None, f"capture failed: {err}"

    captured_id = cap["structuredContent"]["id"]
    assert captured_id

    # Re-capturing the same content must be idempotent (same id).
    again = _call_tool("capture", {"content": content})
    assert _error_text(again) is None
    assert again["structuredContent"]["id"] == captured_id

    time.sleep(0.3)  # let the row settle before the vector search

    res = _call_tool(
        "search", {"query": tag, "match_count": 5, "match_threshold": 0.0}
    )
    assert _error_text(res) is None, f"search failed: {_error_text(res)}"

    # search returns a list -> FastMCP nests it under structuredContent.result
    hits = res["structuredContent"]["result"]
    assert any(tag in hit["content"] for hit in hits), (
        f"captured tag {tag!r} not found in search hits: "
        f"{[h['content'] for h in hits]}"
    )


@requires_server
def test_stats_tool_is_reachable():
    """stats touches no embedding provider, so it always runs when the
    server is up — a transport/auth liveness check independent of any
    key."""
    res = _call_tool("stats", {})
    assert _error_text(res) is None
    stats = res["structuredContent"]
    assert "total_thoughts" in stats
    assert isinstance(stats["total_thoughts"], int)
