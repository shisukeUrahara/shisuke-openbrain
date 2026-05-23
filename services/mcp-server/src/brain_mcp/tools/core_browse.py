"""MCP tool: browse — list recent thoughts chronologically."""
from __future__ import annotations

import json
from typing import Any

from fastmcp import FastMCP

from ..config import Config
from ..db import conn


def register(mcp: FastMCP, *, config: Config) -> None:
    @mcp.tool
    async def browse(
        limit: int = 20,
        since_days: int | None = 7,
    ) -> list[dict[str, Any]]:
        """Browse recent thoughts in reverse chronological order.

        `limit` caps the number of rows returned (max 200).
        `since_days` restricts to rows whose created_at is within the
        last N days; pass null to disable the time filter.
        """
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")

        sql = (
            "SELECT id, content, metadata, created_at "
            "FROM thoughts "
        )
        params: list[Any] = []
        if since_days is not None:
            if since_days < 0:
                raise ValueError("since_days must be non-negative or null")
            sql += "WHERE created_at >= now() - ($1 || ' days')::interval "
            params.append(str(since_days))
        sql += f"ORDER BY created_at DESC LIMIT ${len(params) + 1}"
        params.append(limit)

        async with conn() as connection:
            rows = await connection.fetch(sql, *params)

        return [
            {
                "id": str(row["id"]),
                "content": row["content"],
                "metadata": json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"],
                "created_at": row["created_at"].isoformat(),
            }
            for row in rows
        ]
