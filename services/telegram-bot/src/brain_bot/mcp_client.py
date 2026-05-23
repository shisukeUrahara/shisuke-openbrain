"""Thin HTTP client for the MCP server's tools/call surface.

Only exposes what the bot actually needs (`capture` for the text path).
Workers and other services have their own thin clients; we do not
share one between processes because each caller's auth + URL is
configured independently.
"""
from __future__ import annotations

from typing import Any

import httpx


class McpError(RuntimeError):
    """Raised when the MCP server returns a non-2xx HTTP status or a
    JSON-RPC error object. Carries the raw error so the bot logs the
    cause instead of swallowing it."""


class McpClient:
    def __init__(self, brain_url: str, *, timeout: float = 30.0) -> None:
        if not brain_url:
            raise ValueError("brain_url must be set (include the ?key=)")
        self._url = brain_url
        self._timeout = timeout

    async def capture(
        self,
        content: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Call the MCP `capture` tool. Returns the parsed result dict."""
        rpc = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "capture",
                "arguments": {"content": content, "metadata": metadata or {}},
            },
        }
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                self._url,
                json=rpc,
                headers={"Accept": "application/json"},
            )
        if response.status_code != 200:
            raise McpError(
                f"capture failed: status={response.status_code} body={response.text}"
            )
        payload = response.json()
        if "error" in payload:
            raise McpError(f"capture returned error: {payload['error']}")
        # FastMCP wraps tool returns in result.structuredContent for
        # dict-returning tools.
        try:
            return payload["result"]["structuredContent"]
        except (KeyError, TypeError) as exc:
            raise McpError(f"unexpected response shape: {payload!r}") from exc
