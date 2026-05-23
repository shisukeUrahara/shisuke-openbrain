"""MCP tool: add_chunks — embed and insert chunks for a document.

Each chunk receives its own embedding so passage-level search can
return tight, citation-friendly contexts. Workers (article, PDF,
audio, image) call this after capture_document returns a document id.

The tool is idempotent on (document_id, chunk_index): re-sending the
same chunk updates its content + embedding rather than failing.
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
    async def add_chunks(
        document_id: str,
        chunks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Add embedded chunks to an existing document.

        Each chunk dict must include `content` (str) and `chunk_index`
        (int). Optional: `metadata` (dict).

        Returns {document_id, inserted, updated, total}: how many
        rows were freshly inserted vs updated (re-ingestion), and the
        document's resulting total chunk count.
        """
        if not chunks:
            return {"document_id": document_id, "inserted": 0, "updated": 0, "total": 0}

        # Validate up front so we don't half-write a batch.
        for c in chunks:
            if not isinstance(c, dict):
                raise ValueError(f"chunk must be a dict, got {type(c).__name__}")
            if "content" not in c or not isinstance(c["content"], str):
                raise ValueError("each chunk needs a string 'content' field")
            if "chunk_index" not in c or not isinstance(c["chunk_index"], int):
                raise ValueError("each chunk needs an int 'chunk_index' field")
            if not c["content"].strip():
                raise ValueError("chunk content must be non-empty")

        inserted = 0
        updated = 0

        async with conn() as connection:
            # Confirm the parent document exists; better to fail fast
            # than write orphan chunks the FK would reject anyway.
            doc_row = await connection.fetchval(
                "SELECT id FROM documents WHERE id = $1::uuid", document_id
            )
            if not doc_row:
                raise ValueError(f"document {document_id} does not exist")

            for chunk in chunks:
                vector = await embed(chunk["content"], config=config)
                vec_literal = embedding_literal(vector)
                metadata = chunk.get("metadata") or {}

                result = await connection.fetchrow(
                    """
                    INSERT INTO chunks (document_id, chunk_index, content, embedding, metadata)
                    VALUES ($1::uuid, $2, $3, $4::vector, $5::jsonb)
                    ON CONFLICT (document_id, chunk_index) DO UPDATE
                      SET content   = EXCLUDED.content,
                          embedding = EXCLUDED.embedding,
                          metadata  = EXCLUDED.metadata
                    RETURNING (xmax = 0) AS is_new
                    """,
                    document_id,
                    chunk["chunk_index"],
                    chunk["content"],
                    vec_literal,
                    json.dumps(metadata),
                )
                if result and result["is_new"]:
                    inserted += 1
                else:
                    updated += 1

            total = await connection.fetchval(
                "SELECT count(*) FROM chunks WHERE document_id = $1::uuid",
                document_id,
            )

        return {
            "document_id": document_id,
            "inserted": inserted,
            "updated": updated,
            "total": int(total or 0),
        }
