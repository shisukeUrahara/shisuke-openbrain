"""Integration test fixtures for the MCP server.

Spins an ephemeral Postgres container (pgvector/pgvector:pg17) per test
session, applies the four Phase 1 core migrations, and yields a DSN.
Tests open their own connections — the fixture only manages the
container lifecycle.

Also exposes a `config` fixture that builds a brain_mcp.Config bound
to the ephemeral container (so async tools can be exercised without
real env vars), and a `pool` fixture that owns init_pool / close_pool.

Layer: integration
Phase: 01 / 02
Run:   pytest services/mcp-server/tests/integration -v
"""
from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

import psycopg
import pytest
import pytest_asyncio
from testcontainers.postgres import PostgresContainer


REPO_ROOT = Path(__file__).resolve().parents[4]
SQL_DIR = REPO_ROOT / "sql"
CORE_MIGRATIONS = (
    "000_extensions.sql",
    "001_thoughts.sql",
    "002_match_thoughts.sql",
    "003_dedup.sql",
)


def _connection_url(container: PostgresContainer) -> str:
    """Return a plain psycopg-compatible DSN, stripping any SQLAlchemy driver."""
    url = container.get_connection_url()
    return url.replace("postgresql+psycopg2://", "postgresql://").replace(
        "postgresql+psycopg://", "postgresql://"
    )


def _apply_migrations(dsn: str, migrations: tuple[str, ...]) -> None:
    """Apply each SQL file in order against the given DSN."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        for fname in migrations:
            sql_path = SQL_DIR / fname
            assert sql_path.exists(), f"missing migration: {sql_path}"
            conn.execute(sql_path.read_text())


@pytest.fixture(scope="session")
def pg() -> str:
    """Session-scoped Postgres container with the core schema loaded.

    Returns the connection DSN. Tests should open and close their own
    connections so failures in one test never break the fixture.
    """
    with PostgresContainer("pgvector/pgvector:pg17") as container:
        dsn = _connection_url(container)
        _apply_migrations(dsn, CORE_MIGRATIONS)
        yield dsn


@pytest.fixture
def clean_pg(pg: str) -> str:
    """Per-test fixture that truncates the thoughts table before yielding.

    Use this when a test needs an empty thoughts table at start. Keeps the
    session container alive so we pay container start-up only once.
    """
    with psycopg.connect(pg, autocommit=True) as conn:
        conn.execute("DELETE FROM thoughts WHERE TRUE")
    return pg


# ──────────────────────────────────────────────────────────────────
# Phase 2: Config + asyncpg pool fixtures
# ──────────────────────────────────────────────────────────────────

@pytest.fixture
def config(pg: str, monkeypatch: pytest.MonkeyPatch):
    """Return a brain_mcp.Config bound to the ephemeral container."""
    from brain_mcp.config import load_config

    monkeypatch.setenv("DATABASE_URL", pg)
    monkeypatch.setenv("BRAIN_KEY", "a" * 64)
    # OpenRouter key is intentionally absent — tools that need
    # embeddings will use mocks or the live marker.
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    return load_config(yaml_path=REPO_ROOT / "config" / "features.yaml")


@pytest_asyncio.fixture
async def pool(config) -> AsyncIterator[None]:
    """Initialise and tear down the asyncpg pool around a test."""
    from brain_mcp import db

    await db.init_pool(config)
    try:
        yield
    finally:
        await db.close_pool()
