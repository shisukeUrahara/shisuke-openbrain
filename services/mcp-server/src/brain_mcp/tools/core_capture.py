"""MCP tool: capture — embed and upsert a single thought."""
from __future__ import annotations

import json
from typing import Any

from fastmcp import FastMCP

from ..config import Config
from ..db import conn, embedding_literal
from ..embed import embed


def register(mcp: FastMCP, *, config: Config) -> None:
    @mcp.tool
    async def capture(
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Capture a single thought to the brain.

        Embeds the content via the configured provider, then upserts by
        SHA-256 fingerprint of the normalized content. Repeated calls
        with the same content return the original row id and merge any
        new metadata keys rather than creating a duplicate.

        Returns a dict with `id` (uuid), `fingerprint` (hex), and a
        boolean `embedded` flag — false only if the embedding step
        failed and we fell through to a no-embedding insert.
        """
        if not content or not content.strip():
            raise ValueError("content must be a non-empty string")

        vector = await embed(content, config=config)
        vector_literal = embedding_literal(vector)
        payload = {"metadata": metadata or {}}

        async with conn() as connection:
            upsert_row = await connection.fetchrow(
                "SELECT upsert_thought($1, $2::jsonb) AS result",
                content,
                json.dumps(payload),
            )
            result = json.loads(upsert_row["result"])
            thought_id = result["id"]

            await connection.execute(
                "UPDATE thoughts SET embedding = $1::vector WHERE id = $2",
                vector_literal,
                thought_id,
            )

        return {
            "id": thought_id,
            "fingerprint": result["fingerprint"],
            "embedded": True,
        }
