"""Database helpers for the obsidian listener.

Thin asyncpg wrappers: connect, fetch one document by id, iterate all
documents (for backfill), and a LISTEN helper. We connect directly to
Postgres rather than going through the MCP server because LISTEN/
NOTIFY is a raw-connection feature the MCP tool surface does not
expose.
"""
from __future__ import annotations

from typing import Any, AsyncIterator

import asyncpg


_DOCUMENT_COLUMNS = "id, title, kind, source, content_md, project, created_at"


async def connect(database_url: str) -> asyncpg.Connection:
    return await asyncpg.connect(dsn=database_url)


async def fetch_document(conn: asyncpg.Connection, doc_id: str) -> dict[str, Any] | None:
    row = await conn.fetchrow(
        f"SELECT {_DOCUMENT_COLUMNS} FROM documents WHERE id = $1::uuid",
        doc_id,
    )
    return dict(row) if row else None


async def iter_all_documents(
    conn: asyncpg.Connection,
    *,
    batch_size: int = 200,
) -> AsyncIterator[dict[str, Any]]:
    """Yield every document, oldest first, for the backfill sweep.

    Uses a server-side cursor so a large brain does not load all
    rows into memory at once.
    """
    async with conn.transaction():
        cursor = conn.cursor(
            f"SELECT {_DOCUMENT_COLUMNS} FROM documents ORDER BY created_at ASC"
        )
        async for row in cursor:
            yield dict(row)
