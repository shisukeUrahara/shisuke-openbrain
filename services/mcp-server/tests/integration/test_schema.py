"""Schema integration tests for Phase 1.

Verifies that the four core migrations produce the expected database
objects, that the schema is idempotent, and that upsert_thought
de-duplicates by content fingerprint as specified.

Layer: integration
Phase: 01
Run:   pytest services/mcp-server/tests/integration/test_schema.py -v
"""
from __future__ import annotations

from pathlib import Path

import psycopg
import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
SQL_DIR = REPO_ROOT / "sql"
CORE_MIGRATIONS = (
    "000_extensions.sql",
    "001_thoughts.sql",
    "002_match_thoughts.sql",
    "003_dedup.sql",
)


# ──────────────────────────────────────────────────────────────────
# Extensions
# ──────────────────────────────────────────────────────────────────

def test_required_extensions_installed(pg: str) -> None:
    """The three required extensions (vector, pg_trgm, uuid-ossp) are present."""
    with psycopg.connect(pg) as conn:
        rows = conn.execute("SELECT extname FROM pg_extension").fetchall()
    names = {r[0] for r in rows}
    assert {"vector", "pg_trgm", "uuid-ossp"} <= names


# ──────────────────────────────────────────────────────────────────
# Thoughts table shape
# ──────────────────────────────────────────────────────────────────

def test_thoughts_table_columns_match_spec(pg: str) -> None:
    """The thoughts table has exactly the columns Phase 1 defines."""
    with psycopg.connect(pg) as conn:
        rows = conn.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'thoughts'
            ORDER BY ordinal_position
            """
        ).fetchall()
    cols = {name: dtype for name, dtype in rows}
    expected = {
        "id": "uuid",
        "content": "text",
        "embedding": "USER-DEFINED",  # pgvector reports user-defined type
        "metadata": "jsonb",
        "created_at": "timestamp with time zone",
        "updated_at": "timestamp with time zone",
        "content_fingerprint": "text",
    }
    for col, dtype in expected.items():
        assert col in cols, f"missing column: {col}"
        assert cols[col] == dtype, f"{col}: expected {dtype}, got {cols[col]}"


def test_thoughts_indexes_present(pg: str) -> None:
    """The HNSW vector index, GIN metadata index, btree created_at index,
    and unique partial fingerprint index all exist."""
    with psycopg.connect(pg) as conn:
        rows = conn.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'thoughts'"
        ).fetchall()
    names = {r[0] for r in rows}
    expected = {
        "thoughts_pkey",
        "thoughts_embedding_idx",
        "thoughts_metadata_idx",
        "thoughts_created_at_idx",
        "thoughts_fingerprint_uniq",
    }
    assert expected <= names, f"missing indexes: {expected - names}"


def test_updated_at_trigger_fires_on_update(clean_pg: str) -> None:
    """The thoughts_updated_at trigger updates updated_at on row UPDATE."""
    with psycopg.connect(clean_pg, autocommit=True) as conn:
        row = conn.execute(
            "INSERT INTO thoughts (content) VALUES ('trigger test') RETURNING id, updated_at"
        ).fetchone()
        assert row is not None
        thought_id, original_ts = row

        # Update something and confirm updated_at moves forward.
        new_row = conn.execute(
            "UPDATE thoughts SET content = 'trigger test (updated)' WHERE id = %s RETURNING updated_at",
            (thought_id,),
        ).fetchone()
        assert new_row is not None
        assert new_row[0] > original_ts


# ──────────────────────────────────────────────────────────────────
# Functions
# ──────────────────────────────────────────────────────────────────

def test_match_thoughts_function_exists(pg: str) -> None:
    """The semantic search RPC is registered with the expected signature."""
    with psycopg.connect(pg) as conn:
        row = conn.execute(
            """
            SELECT pg_get_function_identity_arguments(oid)
            FROM pg_proc
            WHERE proname = 'match_thoughts'
            """
        ).fetchone()
    assert row is not None, "match_thoughts function missing"
    args = row[0]
    # Args are in declaration order.
    assert "query_embedding vector" in args
    assert "match_threshold double precision" in args
    assert "match_count integer" in args
    assert "filter jsonb" in args


def test_upsert_thought_function_exists(pg: str) -> None:
    """The upsert_thought function is registered."""
    with psycopg.connect(pg) as conn:
        row = conn.execute(
            "SELECT pg_get_function_identity_arguments(oid) FROM pg_proc WHERE proname = 'upsert_thought'"
        ).fetchone()
    assert row is not None
    assert "p_content text" in row[0]
    assert "p_payload jsonb" in row[0]


# ──────────────────────────────────────────────────────────────────
# upsert_thought behaviour
# ──────────────────────────────────────────────────────────────────

def test_upsert_thought_inserts_new_row(clean_pg: str) -> None:
    """First call with new content inserts a row and returns its id + fingerprint."""
    with psycopg.connect(clean_pg, autocommit=True) as conn:
        result = conn.execute(
            "SELECT upsert_thought(%s, %s)",
            ("hello phase one", "{}"),
        ).fetchone()
    assert result is not None
    payload = result[0]
    assert "id" in payload
    assert "fingerprint" in payload
    assert len(payload["fingerprint"]) == 64  # SHA-256 hex

    with psycopg.connect(clean_pg) as conn:
        n = conn.execute("SELECT count(*) FROM thoughts").fetchone()[0]
    assert n == 1


def test_upsert_thought_dedupes_identical_content(clean_pg: str) -> None:
    """Calling upsert_thought twice with identical content produces one row."""
    with psycopg.connect(clean_pg, autocommit=True) as conn:
        first = conn.execute(
            "SELECT upsert_thought(%s, %s)", ("duplicate me", "{}")
        ).fetchone()[0]
        second = conn.execute(
            "SELECT upsert_thought(%s, %s)", ("duplicate me", "{}")
        ).fetchone()[0]
        n = conn.execute("SELECT count(*) FROM thoughts").fetchone()[0]
    assert first["id"] == second["id"]
    assert first["fingerprint"] == second["fingerprint"]
    assert n == 1


def test_upsert_thought_normalizes_whitespace_and_case(clean_pg: str) -> None:
    """Fingerprint is computed on lower-cased, whitespace-collapsed text,
    so casing and extra spaces should not produce a second row."""
    with psycopg.connect(clean_pg, autocommit=True) as conn:
        a = conn.execute(
            "SELECT upsert_thought(%s, %s)", ("Hello World", "{}")
        ).fetchone()[0]
        b = conn.execute(
            "SELECT upsert_thought(%s, %s)", ("  hello   world  ", "{}")
        ).fetchone()[0]
        n = conn.execute("SELECT count(*) FROM thoughts").fetchone()[0]
    assert a["id"] == b["id"]
    assert n == 1


def test_upsert_thought_merges_metadata_on_duplicate(clean_pg: str) -> None:
    """Re-upserting the same content with new metadata keys should merge."""
    with psycopg.connect(clean_pg, autocommit=True) as conn:
        conn.execute(
            "SELECT upsert_thought(%s, %s)",
            ("merge metadata", '{"metadata": {"source": "first"}}'),
        )
        conn.execute(
            "SELECT upsert_thought(%s, %s)",
            ("merge metadata", '{"metadata": {"tag": "second"}}'),
        )
        row = conn.execute(
            "SELECT metadata FROM thoughts WHERE content = 'merge metadata'"
        ).fetchone()
    assert row is not None
    md = row[0]
    assert md.get("source") == "first"
    assert md.get("tag") == "second"


# ──────────────────────────────────────────────────────────────────
# match_thoughts behaviour
# ──────────────────────────────────────────────────────────────────

def _vec_literal(values: list[float]) -> str:
    """pgvector accepts vectors as a bracketed string with comma-separated floats."""
    return "[" + ",".join(f"{v:.6f}" for v in values) + "]"


def test_match_thoughts_returns_self_at_high_similarity(clean_pg: str) -> None:
    """Inserting a row with a known embedding and searching by the same
    vector should return that row with similarity = 1.0."""
    vec = [0.1] * 1536
    with psycopg.connect(clean_pg, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO thoughts (content, embedding) VALUES (%s, %s::vector)",
            ("self-match probe", _vec_literal(vec)),
        )
        rows = conn.execute(
            "SELECT content, similarity FROM match_thoughts(%s::vector, 0.5, 5, '{}'::jsonb)",
            (_vec_literal(vec),),
        ).fetchall()
    assert len(rows) >= 1
    assert rows[0][0] == "self-match probe"
    assert rows[0][1] == pytest.approx(1.0, abs=1e-6)


def test_match_thoughts_respects_metadata_filter(clean_pg: str) -> None:
    """When a metadata filter is supplied, only rows whose metadata
    contains those keys should be returned."""
    vec = [0.2] * 1536
    with psycopg.connect(clean_pg, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO thoughts (content, embedding, metadata) VALUES "
            "(%s, %s::vector, %s::jsonb)",
            ("included", _vec_literal(vec), '{"project": "ax"}'),
        )
        conn.execute(
            "INSERT INTO thoughts (content, embedding, metadata) VALUES "
            "(%s, %s::vector, %s::jsonb)",
            ("excluded", _vec_literal(vec), '{"project": "other"}'),
        )
        rows = conn.execute(
            "SELECT content FROM match_thoughts(%s::vector, 0.5, 5, %s::jsonb)",
            (_vec_literal(vec), '{"project": "ax"}'),
        ).fetchall()
    contents = {r[0] for r in rows}
    assert "included" in contents
    assert "excluded" not in contents


# ──────────────────────────────────────────────────────────────────
# Idempotency — applying migrations twice must not error
# ──────────────────────────────────────────────────────────────────

def test_core_migrations_are_idempotent(pg: str) -> None:
    """Re-applying every core migration on the already-loaded DB must not
    raise. This is the project-wide guarantee from sql-style.md.
    """
    with psycopg.connect(pg, autocommit=True) as conn:
        for fname in CORE_MIGRATIONS:
            path = SQL_DIR / fname
            conn.execute(path.read_text())  # second application — no errors.
