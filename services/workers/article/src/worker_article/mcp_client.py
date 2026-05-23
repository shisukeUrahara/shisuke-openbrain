"""HTTP client wrapper for the MCP server's documents tools.

Two calls covered: capture_document and add_chunks. Both go through
the JSON-RPC tools/call surface. The brain URL must already carry
?key=… because Telegram-style auth uses the query parameter for
clients that cannot set custom headers.
"""
from __future__ import annotations

from typing import Any

import httpx


class McpError(RuntimeError):
    """Raised on any non-2xx HTTP status or JSON-RPC error payload."""


class McpClient:
    def __init__(
        self,
        brain_url: str,
        *,
        timeout: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not brain_url:
            raise ValueError("brain_url must be set (include the ?key=)")
        self._url = brain_url
        self._timeout = timeout
        self._client = client

    async def capture_document(
        self,
        *,
        title: str,
        kind: str,
        content_md: str,
        source: str,
        sha256: str,
        project: str | None = None,
        summary: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        args = {
            "title": title,
            "kind": kind,
            "content_md": content_md,
            "source": source,
            "sha256": sha256,
        }
        if project is not None:
            args["project"] = project
        if summary is not None:
            args["summary"] = summary
        if metadata is not None:
            args["metadata"] = metadata
        return await self._call_tool("capture_document", args)

    async def add_chunks(
        self,
        *,
        document_id: str,
        chunks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return await self._call_tool(
            "add_chunks",
            {"document_id": document_id, "chunks": chunks},
        )

    async def _call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        rpc = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }

        if self._client is not None:
            response = await self._client.post(
                self._url, json=rpc,
                headers={"Accept": "application/json"},
            )
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    self._url, json=rpc,
                    headers={"Accept": "application/json"},
                )

        if response.status_code != 200:
            raise McpError(
                f"{name} failed: status={response.status_code} body={response.text}"
            )
        payload = response.json()
        # JSON-RPC transport-level error.
        if "error" in payload:
            raise McpError(f"{name} returned error: {payload['error']}")
        result = payload.get("result") or {}
        # Tool-level error: FastMCP sets isError=true and puts the
        # message under result.content[].text instead of
        # structuredContent.
        if result.get("isError"):
            msg = "unknown tool error"
            for item in result.get("content") or []:
                if isinstance(item, dict) and item.get("type") == "text":
                    msg = item.get("text", msg)
                    break
            raise McpError(f"{name} tool error: {msg}")
        try:
            return result["structuredContent"]
        except (KeyError, TypeError) as exc:
            raise McpError(f"unexpected response shape from {name}: {payload!r}") from exc
