"""MCP tool: stats — aggregate brain statistics."""
from __future__ import annotations

from typing import Any

from fastmcp import FastMCP

from ..config import Config
from ..db import conn


def register(mcp: FastMCP, *, config: Config) -> None:
    @mcp.tool
    async def stats() -> dict[str, Any]:
        """Return aggregate statistics about the brain.

        Reports:
        - total_thoughts: total row count in `thoughts`.
        - embedded_thoughts: rows with a non-null embedding (rows can
          temporarily be unembedded if the OpenRouter call failed and
          we are about to retry).
        - rate_last_7d: number of new thoughts created in the last 7
          days.
        - top_topics: most frequent `metadata.topics` values across
          all rows (sourced via jsonb path `topics`). Optional —
          only present once topic taxonomy lands in a later phase.
        """
        async with conn() as connection:
            total = await connection.fetchval(
                "SELECT count(*) FROM thoughts"
            )
            embedded = await connection.fetchval(
                "SELECT count(*) FROM thoughts WHERE embedding IS NOT NULL"
            )
            rate = await connection.fetchval(
                "SELECT count(*) FROM thoughts "
                "WHERE created_at >= now() - interval '7 days'"
            )
            top_rows = await connection.fetch(
                """
                SELECT topic, count(*) AS n
                FROM (
                    SELECT jsonb_array_elements_text(metadata -> 'topics') AS topic
                    FROM thoughts
                    WHERE metadata ? 'topics'
                ) s
                GROUP BY topic
                ORDER BY n DESC
                LIMIT 10
                """
            )

        return {
            "total_thoughts": total or 0,
            "embedded_thoughts": embedded or 0,
            "rate_last_7d": rate or 0,
            "top_topics": [
                {"topic": row["topic"], "count": int(row["n"])}
                for row in top_rows
            ],
        }
