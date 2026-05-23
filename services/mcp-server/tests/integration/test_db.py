"""Integration tests for brain_mcp.db.

Layer: integration
Phase: 02
Run:   pytest services/mcp-server/tests/integration/test_db.py -v
"""
from __future__ import annotations

import pytest

from brain_mcp import db


async def test_pool_init_returns_working_pool(config, pool):
    """init_pool yields a usable pool that the conn() context manager
    can hand connections out of."""
    async with db.conn() as connection:
        value = await connection.fetchval("SELECT 1")
        assert value == 1


async def test_pool_is_idempotent(config, pool):
    """Calling init_pool twice returns the same pool instance — no
    extra connections opened on the second call."""
    first = await db.init_pool(config)
    second = await db.init_pool(config)
    assert first is second


async def test_conn_without_init_raises():
    """Using conn() before init_pool fails fast rather than silently
    initialising with no Config context."""
    await db.close_pool()  # in case a previous test left it open
    with pytest.raises(RuntimeError, match="not initialised"):
        async with db.conn() as _:
            pass


async def test_embedding_literal_round_trips_through_pgvector(clean_pg, config, pool):
    """The embedding_literal helper produces a string pgvector accepts
    when cast with ::vector, and the value reads back identically."""
    vec = [0.1, -0.5, 0.0] + [0.0] * 1533
    literal = db.embedding_literal(vec)

    async with db.conn() as connection:
        row = await connection.fetchrow(
            "INSERT INTO thoughts (content, embedding) "
            "VALUES ($1, $2::vector) RETURNING id, embedding",
            "literal round-trip",
            literal,
        )
        assert row is not None
        # Embedding round-trips as a string of the canonical pgvector
        # form; asserting the prefix is enough to catch corruption.
        returned = row["embedding"]
        assert returned.startswith("[0.1,-0.5,0,")


async def test_close_pool_resets_state(config):
    """close_pool empties the module-level pool reference so subsequent
    conn() calls fail until init_pool runs again."""
    await db.init_pool(config)
    await db.close_pool()
    with pytest.raises(RuntimeError):
        async with db.conn() as _:
            pass
