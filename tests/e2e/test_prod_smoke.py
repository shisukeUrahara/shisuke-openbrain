"""Production smoke — assert a *deployed* MCP server is healthy and live.

Black-box, like test_capture_search_loop, but aimed at a real
deployment behind TLS. Parametrised entirely by env:

    BRAIN_URL   full MCP endpoint, e.g. https://brain.example.com/mcp
    BRAIN_KEY   the bearer key

When BRAIN_URL is unset (the normal case in local CI) every test skips —
this suite only means anything against a deployment. Point it at the
VPS after Phase 6 deploy:

    BRAIN_URL=https://brain.example.com/mcp BRAIN_KEY=... \
        pytest tests/e2e/test_prod_smoke.py -v

The capture/search test additionally skips if the deployed server has
no embedding provider, same as the local e2e loop.
"""
from __future__ import annotations

import json
import os
import uuid

import httpx
import pytest


BRAIN_URL = os.environ.get("BRAIN_URL")
KEY = os.environ.get("BRAIN_KEY")

pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        not BRAIN_URL or not KEY,
        reason="set BRAIN_URL (deployed /mcp endpoint) and BRAIN_KEY to run",
    ),
]

HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

CORE_TOOLS = {"capture", "search", "browse", "stats"}


def _health_url() -> str:
    # BRAIN_URL ends in /mcp (optionally with ?key=...); /health is a
    # sibling path on the same origin.
    base = BRAIN_URL.split("?", 1)[0].rstrip("/")
    if base.endswith("/mcp"):
        base = base[: -len("/mcp")]
    return base.rstrip("/") + "/health"


def _parse(text: str) -> dict:
    text = text.strip()
    if text.startswith("data:") or "\ndata:" in text:
        for line in reversed(text.splitlines()):
            if line.startswith("data:"):
                return json.loads(line[len("data:") :].strip())
    return json.loads(text)


def _rpc(method: str, params: dict, *, key: str | None = None) -> httpx.Response:
    use_key = KEY if key is None else key
    with httpx.Client(timeout=30.0) as client:
        return client.post(
            BRAIN_URL.split("?", 1)[0],
            headers={**HEADERS, "x-brain-key": use_key},
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
        )


def _result(method: str, params: dict) -> dict:
    r = _rpc(method, params)
    r.raise_for_status()
    body = _parse(r.text)
    assert "error" not in body, f"transport error: {body.get('error')}"
    return body["result"]


def _error_text(result: dict) -> str | None:
    if not result.get("isError"):
        return None
    for item in result.get("content") or []:
        if isinstance(item, dict) and item.get("type") == "text":
            return item.get("text", "tool error")
    return "tool error"


def test_endpoint_is_https():
    """A production deployment must be behind TLS."""
    assert BRAIN_URL.startswith("https://"), (
        f"BRAIN_URL is not https: {BRAIN_URL!r} — fine for a tunnel, "
        "but a real deployment must terminate TLS"
    )


def test_health_ok():
    r = httpx.get(_health_url(), timeout=10.0)
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_tools_list_has_core_tools():
    """At least the 4 core tools are present. Uses >= so the test
    survives the operator enabling module flags in production."""
    tools = _result("tools/list", {})["tools"]
    names = {t["name"] for t in tools}
    assert CORE_TOOLS <= names, f"missing core tools: {CORE_TOOLS - names}"
    assert len(tools) >= 4


def test_wrong_key_is_rejected():
    """A bad bearer key must be refused at the auth layer (401),
    never reach a tool."""
    r = _rpc("tools/list", {}, key="definitely-wrong-key")
    assert r.status_code == 401


def test_capture_then_search_finds_it():
    tag = f"prod-{uuid.uuid4().hex[:8]}"
    cap = _result("tools/call", {"name": "capture", "arguments": {"content": f"prod smoke {tag}"}})
    err = _error_text(cap)
    if err and "embed" in err.lower():
        pytest.skip(f"deployed server has no embedding provider: {err}")
    assert err is None, f"capture failed: {err}"

    res = _result(
        "tools/call",
        {"name": "search", "arguments": {"query": tag, "match_count": 5, "match_threshold": 0.0}},
    )
    assert _error_text(res) is None
    hits = res["structuredContent"]["result"]
    assert any(tag in hit["content"] for hit in hits)
