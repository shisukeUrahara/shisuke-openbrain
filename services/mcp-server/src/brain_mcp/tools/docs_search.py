"""MCP tool: search_chunks — semantic passage search across documents.

Calls the match_chunks RPC. The result rows include document title +
source, so a single hit is enough context for the AI to cite the
passage back to the user.
"""
from __future__ import annotations

import json
from typing import Any

from fastmcp import FastMCP

from ..config import Config
from ..db import conn, embedding_literal
from ..embed import embed


def register(mcp: FastMCP, *, config: Config) -> None:
    @mcp.tool
    async def search_chunks(
        query: str,
        match_count: int = 8,
        match_threshold: float = 0.5,
        document_id: str | None = None,
        project: str | None = None,
    ) -> list[dict[str, Any]]:
        """Semantic search across document chunks.

        Embeds `query`, then returns the top `match_count` chunks whose
        cosine similarity exceeds `match_threshold`. Optional filters
        narrow the search to a single document or a project tag.

        Returns dicts with: id, document_id, document_title,
        document_source, chunk_index, content, metadata, similarity,
        created_at.
        """
        if not query or not query.strip():
            raise ValueError("query must be a non-empty string")
        if match_count < 1 or match_count > 100:
            raise ValueError("match_count must be between 1 and 100")
        if not 0.0 <= match_threshold <= 1.0:
            raise ValueError("match_threshold must be between 0.0 and 1.0")

        vector = await embed(query, config=config)
        vec_literal = embedding_literal(vector)

        async with conn() as connection:
            rows = await connection.fetch(
                "SELECT id, document_id, document_title, document_source, "
                "       chunk_index, content, metadata, similarity, created_at "
                "FROM match_chunks($1::vector, $2, $3, $4::uuid, $5)",
                vec_literal,
                match_threshold,
                match_count,
                document_id,
                project,
            )

        return [
            {
                "id": str(row["id"]),
                "document_id": str(row["document_id"]),
                "document_title": row["document_title"],
                "document_source": row["document_source"],
                "chunk_index": int(row["chunk_index"]),
                "content": row["content"],
                "metadata": json.loads(row["metadata"]) if isinstance(row["metadata"], str) else row["metadata"],
                "similarity": float(row["similarity"]),
                "created_at": row["created_at"].isoformat(),
            }
            for row in rows
        ]
