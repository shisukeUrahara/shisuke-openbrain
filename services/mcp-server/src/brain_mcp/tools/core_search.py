"""MCP tool: search — semantic search across captured thoughts."""
from __future__ import annotations

import json
from typing import Any

from fastmcp import FastMCP

from ..config import Config
from ..db import conn, embedding_literal
from ..embed import embed


def register(mcp: FastMCP, *, config: Config) -> None:
    @mcp.tool
    async def search(
        query: str,
        match_count: int = 10,
        match_threshold: float = 0.5,
        metadata_filter: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search across captured thoughts.

        Embeds the query, then calls match_thoughts to return the
        top `match_count` rows whose cosine similarity exceeds
        `match_threshold`. Optional `metadata_filter` is a JSON object
        that must be contained by each result's metadata
        (Postgres jsonb @> operator).

        Returns a list of {id, content, metadata, similarity,
        created_at} dicts ordered by descending similarity.
        """
        if not query or not query.strip():
            raise ValueError("query must be a non-empty string")
        if match_count < 1 or match_count > 100:
            raise ValueError("match_count must be between 1 and 100")
        if not 0.0 <= match_threshold <= 1.0:
            raise ValueError("match_threshold must be between 0.0 and 1.0")

        vector = await embed(query, config=config)
        vector_literal = embedding_literal(vector)
        filter_json = json.dumps(metadata_filter or {})

        async with conn() as connection:
            rows = await connection.fetch(
                "SELECT id, content, metadata, similarity, created_at "
                "FROM match_thoughts($1::vector, $2, $3, $4::jsonb)",
                vector_literal,
                match_threshold,
                match_count,
                filter_json,
            )

        return [
            {
                "id": str(row["id"]),
                "content": row["content"],
                "metadata": json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"],
                "similarity": float(row["similarity"]),
                "created_at": row["created_at"].isoformat(),
            }
            for row in rows
        ]
