"""Integration tests for the documents module schema.

Loads the optional documents migrations onto a fresh testcontainers
Postgres and verifies the new tables, indexes, and match_chunks RPC
behave as the module contract promises. Re-applies the same files a
second time to prove idempotency.

Layer: integration
Phase: 10
Run:   pytest services/mcp-server/tests/integration/test_documents_schema.py -v
"""
from __future__ import annotations

from pathlib import Path

import psycopg
import pytest
import pytest_asyncio


REPO_ROOT = Path(__file__).resolve().parents[4]
DOCS_DIR = REPO_ROOT / "sql" / "modules" / "documents"
DOCS_MIGRATIONS = (
    "010_documents.sql",
    "011_chunks.sql",
    "012_match_chunks.sql",
)


@pytest.fixture
def docs_pg(pg: str):
    """Apply the documents module migrations onto the session pg
    container and return the DSN. Truncates rows between tests so
    each test starts clean."""
    with psycopg.connect(pg, autocommit=True) as conn:
        for fname in DOCS_MIGRATIONS:
            conn.execute((DOCS_DIR / fname).read_text())
        # Clean any leftover rows from previous tests.
        conn.execute("DELETE FROM chunks WHERE TRUE")
        conn.execute("DELETE FROM documents WHERE TRUE")
    return pg


# ──────────────────────────────────────────────────────────────────
# Table shape
# ──────────────────────────────────────────────────────────────────

def test_documents_table_columns_match_spec(docs_pg: str):
    with psycopg.connect(docs_pg) as conn:
        rows = conn.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_name = 'documents'
            ORDER BY ordinal_position
            """
        ).fetchall()
    cols = {name: dtype for name, dtype in rows}
    expected = {
        "id": "uuid",
        "title": "text",
        "kind": "text",
        "source": "text",
        "content_md": "text",
        "summary": "text",
        "summary_embedding": "USER-DEFINED",
        "metadata": "jsonb",
        "project": "text",
        "sha256": "text",
        "created_at": "timestamp with time zone",
        "updated_at": "timestamp with time zone",
    }
    for col, dtype in expected.items():
        assert col in cols, f"missing column: {col}"
        assert cols[col] == dtype, f"{col}: {cols[col]} != {dtype}"


def test_chunks_table_columns_match_spec(docs_pg: str):
    with psycopg.connect(docs_pg) as conn:
        rows = conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = 'chunks' ORDER BY ordinal_position"
        ).fetchall()
    cols = {name: dtype for name, dtype in rows}
    expected = {
        "id": "uuid",
        "document_id": "uuid",
        "chunk_index": "integer",
        "content": "text",
        "embedding": "USER-DEFINED",
        "metadata": "jsonb",
        "created_at": "timestamp with time zone",
    }
    for col, dtype in expected.items():
        assert col in cols, f"missing column: {col}"
        assert cols[col] == dtype, f"{col}: {cols[col]} != {dtype}"


# ──────────────────────────────────────────────────────────────────
# Indexes
# ──────────────────────────────────────────────────────────────────

def test_documents_indexes_present(docs_pg: str):
    with psycopg.connect(docs_pg) as conn:
        rows = conn.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'documents'"
        ).fetchall()
    names = {r[0] for r in rows}
    expected = {
        "documents_pkey",
        "documents_sha256_uniq",
        "documents_summary_embedding_idx",
        "documents_kind_idx",
        "documents_project_idx",
        "documents_created_idx",
        "documents_metadata_idx",
    }
    assert expected <= names, f"missing: {expected - names}"


def test_chunks_indexes_present(docs_pg: str):
    with psycopg.connect(docs_pg) as conn:
        rows = conn.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename = 'chunks'"
        ).fetchall()
    names = {r[0] for r in rows}
    expected = {
        "chunks_pkey",
        "chunks_document_index_uniq",
        "chunks_embedding_idx",
        "chunks_document_idx",
        "chunks_metadata_idx",
    }
    assert expected <= names, f"missing: {expected - names}"


# ──────────────────────────────────────────────────────────────────
# Foreign key + cascade
# ──────────────────────────────────────────────────────────────────

def test_chunk_cascades_when_document_deleted(docs_pg: str):
    with psycopg.connect(docs_pg, autocommit=True) as conn:
        doc_id = conn.execute(
            "INSERT INTO documents (title, kind) VALUES ('cascade probe', 'note') "
            "RETURNING id"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO chunks (document_id, chunk_index, content) "
            "VALUES ($1::uuid, 0, 'chunk 0'), ($1::uuid, 1, 'chunk 1')".replace("$1::uuid", "%s::uuid"),
            (str(doc_id), str(doc_id)),
        )
        assert conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == 2

        conn.execute("DELETE FROM documents WHERE id = %s", (doc_id,))
        assert conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0


def test_chunk_document_index_uniqueness(docs_pg: str):
    """Inserting two chunks at the same chunk_index for one document
    must violate the unique (document_id, chunk_index) constraint."""
    with psycopg.connect(docs_pg, autocommit=True) as conn:
        doc_id = conn.execute(
            "INSERT INTO documents (title, kind) VALUES ('uniq probe', 'note') "
            "RETURNING id"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO chunks (document_id, chunk_index, content) "
            "VALUES (%s, 0, 'a')",
            (doc_id,),
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(
                "INSERT INTO chunks (document_id, chunk_index, content) "
                "VALUES (%s, 0, 'b')",
                (doc_id,),
            )


# ──────────────────────────────────────────────────────────────────
# documents.sha256 partial unique index
# ──────────────────────────────────────────────────────────────────

def test_documents_sha256_unique_when_present(docs_pg: str):
    with psycopg.connect(docs_pg, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO documents (title, kind, sha256) VALUES ('a', 'note', 'abc')"
        )
        with pytest.raises(psycopg.errors.UniqueViolation):
            conn.execute(
                "INSERT INTO documents (title, kind, sha256) VALUES ('b', 'note', 'abc')"
            )


def test_documents_sha256_allows_multiple_nulls(docs_pg: str):
    """The unique index is partial (sha256 IS NOT NULL) so legacy rows
    without a hash do not collide."""
    with psycopg.connect(docs_pg, autocommit=True) as conn:
        conn.execute("INSERT INTO documents (title, kind) VALUES ('x', 'note')")
        conn.execute("INSERT INTO documents (title, kind) VALUES ('y', 'note')")
        n = conn.execute("SELECT count(*) FROM documents WHERE sha256 IS NULL").fetchone()[0]
        assert n == 2


# ──────────────────────────────────────────────────────────────────
# match_chunks RPC
# ──────────────────────────────────────────────────────────────────

def _vec(values: list[float]) -> str:
    return "[" + ",".join(f"{v:.6f}" for v in values) + "]"


def test_match_chunks_returns_self_at_high_similarity(docs_pg: str):
    vec = [0.1] * 1536
    with psycopg.connect(docs_pg, autocommit=True) as conn:
        doc_id = conn.execute(
            "INSERT INTO documents (title, kind, project) "
            "VALUES ('chunk search', 'article', 'ax') RETURNING id"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO chunks (document_id, chunk_index, content, embedding) "
            "VALUES (%s, 0, 'first paragraph', %s::vector)",
            (doc_id, _vec(vec)),
        )
        rows = conn.execute(
            "SELECT document_title, similarity FROM match_chunks(%s::vector, 0.5, 5)",
            (_vec(vec),),
        ).fetchall()
    assert rows
    assert rows[0][0] == "chunk search"
    assert rows[0][1] == pytest.approx(1.0, abs=1e-6)


def test_match_chunks_filter_by_document(docs_pg: str):
    vec = [0.2] * 1536
    with psycopg.connect(docs_pg, autocommit=True) as conn:
        a = conn.execute(
            "INSERT INTO documents (title, kind) VALUES ('doc A', 'article') RETURNING id"
        ).fetchone()[0]
        b = conn.execute(
            "INSERT INTO documents (title, kind) VALUES ('doc B', 'article') RETURNING id"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO chunks (document_id, chunk_index, content, embedding) "
            "VALUES (%s, 0, 'in A', %s::vector)",
            (a, _vec(vec)),
        )
        conn.execute(
            "INSERT INTO chunks (document_id, chunk_index, content, embedding) "
            "VALUES (%s, 0, 'in B', %s::vector)",
            (b, _vec(vec)),
        )
        rows = conn.execute(
            "SELECT content FROM match_chunks(%s::vector, 0.5, 5, %s::uuid)",
            (_vec(vec), a),
        ).fetchall()
    contents = {r[0] for r in rows}
    assert "in A" in contents
    assert "in B" not in contents


def test_match_chunks_filter_by_project(docs_pg: str):
    vec = [0.3] * 1536
    with psycopg.connect(docs_pg, autocommit=True) as conn:
        ax = conn.execute(
            "INSERT INTO documents (title, kind, project) VALUES ('ax doc', 'article', 'ax') RETURNING id"
        ).fetchone()[0]
        other = conn.execute(
            "INSERT INTO documents (title, kind, project) VALUES ('other doc', 'article', 'other') RETURNING id"
        ).fetchone()[0]
        for doc, content in [(ax, "ax chunk"), (other, "other chunk")]:
            conn.execute(
                "INSERT INTO chunks (document_id, chunk_index, content, embedding) "
                "VALUES (%s, 0, %s, %s::vector)",
                (doc, content, _vec(vec)),
            )
        rows = conn.execute(
            "SELECT content FROM match_chunks(%s::vector, 0.5, 5, NULL, 'ax')",
            (_vec(vec),),
        ).fetchall()
    contents = {r[0] for r in rows}
    assert "ax chunk" in contents
    assert "other chunk" not in contents


# ──────────────────────────────────────────────────────────────────
# Idempotency
# ──────────────────────────────────────────────────────────────────

def test_documents_migrations_are_idempotent(docs_pg: str):
    """Re-applying the documents migrations on a DB that already has
    them must not error and must not change the schema."""
    with psycopg.connect(docs_pg, autocommit=True) as conn:
        for fname in DOCS_MIGRATIONS:
            conn.execute((DOCS_DIR / fname).read_text())
