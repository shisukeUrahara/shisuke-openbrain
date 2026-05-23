"""Unit tests for brain_bot.mcp_client.

Mock the MCP server at the httpx wire level. Confirms request shape
(JSON-RPC tools/call with the right arguments) and error surfacing
on HTTP and protocol-level failures.

Layer: unit
Phase: 11
Run:   pytest services/telegram-bot/tests/unit/test_mcp_client.py -v
"""
from __future__ import annotations

import json

import httpx
import pytest

from brain_bot.mcp_client import McpClient, McpError


def _patch_httpx(monkeypatch: pytest.MonkeyPatch, handler) -> None:
    transport = httpx.MockTransport(handler)
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: real_client(transport=transport, **kw),
    )


def _success_response(payload: dict) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "result": {"structuredContent": payload, "isError": False},
        },
    )


# ──────────────────────────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────────────────────────

async def test_capture_sends_jsonrpc_tools_call(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.read())
        return _success_response({"id": "abc", "fingerprint": "f" * 64, "embedded": True})

    _patch_httpx(monkeypatch, handler)

    client = McpClient("http://mcp/mcp?key=xyz")
    result = await client.capture("hello", metadata={"source": "test"})

    assert result["id"] == "abc"
    body = captured["body"]
    assert body["jsonrpc"] == "2.0"
    assert body["method"] == "tools/call"
    assert body["params"]["name"] == "capture"
    assert body["params"]["arguments"]["content"] == "hello"
    assert body["params"]["arguments"]["metadata"] == {"source": "test"}


async def test_capture_defaults_metadata_to_empty_dict(monkeypatch):
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(request.read())
        return _success_response({"id": "x", "fingerprint": "y", "embedded": True})

    _patch_httpx(monkeypatch, handler)
    client = McpClient("http://mcp/mcp")
    await client.capture("just text")
    assert captured["body"]["params"]["arguments"]["metadata"] == {}


# ──────────────────────────────────────────────────────────────────
# Error paths
# ──────────────────────────────────────────────────────────────────

async def test_non_200_raises_with_body(monkeypatch):
    _patch_httpx(monkeypatch, lambda req: httpx.Response(503, text="upstream busy"))
    client = McpClient("http://mcp/mcp")
    with pytest.raises(McpError, match="503"):
        await client.capture("x")


async def test_jsonrpc_error_payload_raises(monkeypatch):
    _patch_httpx(monkeypatch, lambda req: httpx.Response(
        200,
        json={
            "jsonrpc": "2.0", "id": 1,
            "error": {"code": -32600, "message": "Bad Request"},
        },
    ))
    client = McpClient("http://mcp/mcp")
    with pytest.raises(McpError, match="Bad Request"):
        await client.capture("x")


async def test_unexpected_response_shape_raises(monkeypatch):
    _patch_httpx(monkeypatch, lambda req: httpx.Response(
        200,
        json={"unexpected": "shape"},
    ))
    client = McpClient("http://mcp/mcp")
    with pytest.raises(McpError, match="unexpected response shape"):
        await client.capture("x")


# ──────────────────────────────────────────────────────────────────
# Construction
# ──────────────────────────────────────────────────────────────────

def test_empty_brain_url_raises_at_construction():
    with pytest.raises(ValueError, match="brain_url"):
        McpClient("")
