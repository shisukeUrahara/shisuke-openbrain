"""MCP tool: capture_document — register a long-form document.

Embeds the document's summary (or, when no summary is supplied, the
first ~2k chars of content_md) and inserts a row. If a `sha256` hash
is provided AND a row with that hash already exists, returns the
existing row's id with `duplicate: true` so client workers can skip
the chunking step.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from fastmcp import FastMCP

from ..config import Config
from ..db import conn, embedding_literal
from ..embed import embed


_SUMMARY_FALLBACK_LEN = 2000


def register(mcp: FastMCP, *, config: Config) -> None:
    @mcp.tool
    async def capture_document(
        title: str,
        kind: str,
        content_md: str | None = None,
        source: str | None = None,
        summary: str | None = None,
        project: str | None = None,
        sha256: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Register a long-form document.

        `kind` is a free-form label such as 'article', 'pdf',
        'youtube', 'voice', or 'image'. If `sha256` is omitted, we
        compute one over `content_md`. The summary_embedding is built
        from `summary` when present; otherwise from the leading
        characters of `content_md`. Returns:
            {id, sha256, duplicate, embedded}
        `duplicate` is true iff a document with the same sha256 was
        already present.
        """
        if not title or not title.strip():
            raise ValueError("title must be a non-empty string")
        if not kind or not kind.strip():
            raise ValueError("kind must be a non-empty string")

        if sha256 is None and content_md is not None:
            sha256 = hashlib.sha256(content_md.encode("utf-8")).hexdigest()

        async with conn() as connection:
            existing = None
            if sha256:
                existing = await connection.fetchrow(
                    "SELECT id, sha256 FROM documents WHERE sha256 = $1",
                    sha256,
                )
            if existing:
                return {
                    "id": str(existing["id"]),
                    "sha256": existing["sha256"],
                    "duplicate": True,
                    "embedded": False,
                }

            # Build a summary embedding from the best material we have.
            seed_text = (
                summary
                if (summary and summary.strip())
                else (content_md[:_SUMMARY_FALLBACK_LEN] if content_md else "")
            )
            summary_vec_literal: str | None = None
            if seed_text.strip():
                vector = await embed(seed_text, config=config)
                summary_vec_literal = embedding_literal(vector)

            row = await connection.fetchrow(
                """
                INSERT INTO documents
                  (title, kind, source, content_md, summary,
                   summary_embedding, project, sha256, metadata)
                VALUES ($1, $2, $3, $4, $5,
                        $6::vector, $7, $8, $9::jsonb)
                RETURNING id, sha256
                """,
                title,
                kind,
                source,
                content_md,
                summary,
                summary_vec_literal,
                project,
                sha256,
                json.dumps(metadata or {}),
            )

        return {
            "id": str(row["id"]),
            "sha256": row["sha256"],
            "duplicate": False,
            "embedded": summary_vec_literal is not None,
        }
