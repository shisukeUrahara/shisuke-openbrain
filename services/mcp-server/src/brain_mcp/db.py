"""Postgres connection pool.

Owns the single asyncpg `Pool` for the process and exposes a small
async context manager (`conn`) that yields a connection from the
pool. Tools should always go through `conn()` — never acquire the
pool directly — so connection accounting stays in one place.

pgvector embeddings are written as string-literal casts (e.g.
`'[0.1,0.2,...]'::vector`) which avoids registering a custom asyncpg
type codec. The helper `embedding_literal` encapsulates that format.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator, Sequence

import asyncpg

from .config import Config

_pool: asyncpg.Pool | None = None


async def init_pool(config: Config) -> asyncpg.Pool:
    """Create the process-wide asyncpg pool. Idempotent — subsequent
    calls return the existing pool unchanged."""
    global _pool
    if _pool is None:
        _pool = await asyncpg.create_pool(
            dsn=config.database_url,
            min_size=2,
            max_size=10,
            command_timeout=30,
        )
    return _pool


async def close_pool() -> None:
    """Tear the pool down. Used by tests and graceful-shutdown paths."""
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def conn() -> AsyncIterator[asyncpg.Connection]:
    """Yield a pooled connection.

    Raises RuntimeError if init_pool has not been called yet — fail
    fast rather than silently lazy-init with no Config context.
    """
    if _pool is None:
        raise RuntimeError(
            "asyncpg pool not initialised; call init_pool(config) "
            "during application startup"
        )
    async with _pool.acquire() as connection:
        yield connection


def embedding_literal(vector: Sequence[float]) -> str:
    """Format a vector as the pgvector string literal `'[a,b,c]'`.

    Use with a `::vector` cast in the SQL — pgvector parses this form
    without needing a registered asyncpg codec. Floats render with
    full precision; pgvector is tolerant of either bare floats or
    scientific notation.
    """
    return "[" + ",".join(format(float(x), "g") for x in vector) + "]"
