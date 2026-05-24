"""Integration test for the obsidian module's NOTIFY trigger.

Applies the documents migrations + the obsidian notify trigger on a
fresh container, opens a LISTEN, inserts a document, and asserts the
notification fires with the right payload.

Layer: integration
Phase: 13
Run:   pytest services/mcp-server/tests/integration/test_obsidian_notify.py -v
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import asyncpg
import psycopg
import pytest
import pytest_asyncio


REPO_ROOT = Path(__file__).resolve().parents[4]
SQL_DIR = REPO_ROOT / "sql"
DOCS_DIR = SQL_DIR / "modules" / "documents"
OBSIDIAN_DIR = SQL_DIR / "modules" / "obsidian"


@pytest.fixture
def notify_pg(pg: str):
    """Apply documents migrations + obsidian notify trigger."""
    with psycopg.connect(pg, autocommit=True) as conn:
        for fname in ("010_documents.sql", "011_chunks.sql", "012_match_chunks.sql"):
            conn.execute((DOCS_DIR / fname).read_text())
        conn.execute((OBSIDIAN_DIR / "020_notify_document.sql").read_text())
        conn.execute("DELETE FROM documents WHERE TRUE")
    return pg


def test_notify_trigger_exists(notify_pg: str):
    with psycopg.connect(notify_pg) as conn:
        row = conn.execute(
            "SELECT tgname FROM pg_trigger WHERE tgname = 'documents_notify_trigger'"
        ).fetchone()
    assert row is not None


def test_notify_function_exists(notify_pg: str):
    with psycopg.connect(notify_pg) as conn:
        row = conn.execute(
            "SELECT proname FROM pg_proc WHERE proname = 'notify_new_document'"
        ).fetchone()
    assert row is not None


async def test_insert_fires_notification(notify_pg: str):
    """Inserting a document should emit a new_document NOTIFY whose
    payload carries the new row's id, title, kind, and project."""
    received: list[dict] = []

    listener = await asyncpg.connect(dsn=notify_pg)
    inserter = await asyncpg.connect(dsn=notify_pg)
    try:
        loop = asyncio.get_running_loop()
        fired = loop.create_future()

        def _on_notify(_conn, _pid, _channel, payload):
            received.append(json.loads(payload))
            if not fired.done():
                fired.set_result(True)

        await listener.add_listener("new_document", _on_notify)

        await inserter.execute(
            "INSERT INTO documents (title, kind, project) "
            "VALUES ($1, $2, $3)",
            "Notify Probe",
            "article",
            "ax",
        )

        # Wait up to 5s for the notification to arrive.
        await asyncio.wait_for(fired, timeout=5.0)
    finally:
        await listener.close()
        await inserter.close()

    assert len(received) == 1
    payload = received[0]
    assert payload["title"] == "Notify Probe"
    assert payload["kind"] == "article"
    assert payload["project"] == "ax"
    assert "id" in payload


async def test_notify_idempotent_reapply(notify_pg: str):
    """Re-applying the trigger migration must not error or create a
    second trigger."""
    async_conn = await asyncpg.connect(dsn=notify_pg)
    try:
        await async_conn.execute((OBSIDIAN_DIR / "020_notify_document.sql").read_text())
        count = await async_conn.fetchval(
            "SELECT count(*) FROM pg_trigger WHERE tgname = 'documents_notify_trigger'"
        )
        assert count == 1
    finally:
        await async_conn.close()
