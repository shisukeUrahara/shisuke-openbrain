"""Integration tests for the documents-module MCP tools.

The tools are invoked directly as Python coroutines via FastMCP's
get_tool lookup, with the embed provider patched at the httpx layer
so similarity assertions are deterministic.

Layer: integration
Phase: 10
Run:   pytest services/mcp-server/tests/integration/test_tools_documents.py -v
"""
from __future__ import annotations

import hashlib
from pathlib import Path

import httpx
import psycopg
import pytest
import pytest_asyncio
from fastmcp import FastMCP

from brain_mcp import db
from brain_mcp.tools import docs_capture, docs_chunks, docs_search


REPO_ROOT = Path(__file__).resolve().parents[4]
DOCS_DIR = REPO_ROOT / "sql" / "modules" / "documents"
DOCS_MIGRATIONS = (
    "010_documents.sql",
    "011_chunks.sql",
    "012_match_chunks.sql",
)


def _stub_openrouter(monkeypatch: pytest.MonkeyPatch, vector: list[float]) -> None:
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, json={"data": [{"embedding": vector}]})
    )
    real_client = httpx.AsyncClient
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda **kw: real_client(transport=transport, **kw),
    )


@pytest.fixture
def docs_pg(pg: str):
    with psycopg.connect(pg, autocommit=True) as conn:
        for fname in DOCS_MIGRATIONS:
            conn.execute((DOCS_DIR / fname).read_text())
        conn.execute("DELETE FROM chunks WHERE TRUE")
        conn.execute("DELETE FROM documents WHERE TRUE")
    return pg


@pytest_asyncio.fixture
async def mcp_docs(docs_pg, config, pool):
    from dataclasses import replace

    cfg = replace(config, openrouter_api_key="sk-or-test")
    mcp = FastMCP(name="test-docs")
    docs_capture.register(mcp, config=cfg)
    docs_chunks.register(mcp, config=cfg)
    docs_search.register(mcp, config=cfg)
    return mcp


async def _call(mcp: FastMCP, name: str, args: dict):
    tool = await mcp.get_tool(name)
    return await tool.fn(**args)


# ──────────────────────────────────────────────────────────────────
# capture_document
# ──────────────────────────────────────────────────────────────────

async def test_capture_document_inserts_with_embedded_summary(mcp_docs, monkeypatch):
    _stub_openrouter(monkeypatch, [0.1] * 1536)
    result = await _call(mcp_docs, "capture_document", {
        "title": "Test article",
        "kind": "article",
        "source": "https://example.com/x",
        "content_md": "# Heading\n\nbody body body" * 50,
        "summary": "short summary",
        "project": "ax",
        "metadata": {"author": "me"},
    })
    assert result["duplicate"] is False
    assert result["embedded"] is True
    assert len(result["sha256"]) == 64

    async with db.conn() as connection:
        row = await connection.fetchrow(
            "SELECT title, project, summary, summary_embedding IS NOT NULL AS has_embed "
            "FROM documents WHERE id = $1::uuid",
            result["id"],
        )
    assert row["title"] == "Test article"
    assert row["project"] == "ax"
    assert row["summary"] == "short summary"
    assert row["has_embed"] is True


async def test_capture_document_auto_hashes_when_sha256_omitted(mcp_docs, monkeypatch):
    _stub_openrouter(monkeypatch, [0.2] * 1536)
    body = "deterministic content"
    expected = hashlib.sha256(body.encode("utf-8")).hexdigest()
    result = await _call(mcp_docs, "capture_document", {
        "title": "auto-hash", "kind": "note",
        "content_md": body,
    })
    assert result["sha256"] == expected


async def test_capture_document_dedupes_by_sha256(mcp_docs, monkeypatch):
    _stub_openrouter(monkeypatch, [0.3] * 1536)
    first = await _call(mcp_docs, "capture_document", {
        "title": "dup", "kind": "note", "content_md": "same body", "sha256": "abc123",
    })
    second = await _call(mcp_docs, "capture_document", {
        "title": "dup again", "kind": "note", "content_md": "different body", "sha256": "abc123",
    })
    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert second["id"] == first["id"]
    assert second["embedded"] is False  # duplicates skip the embed step


async def test_capture_document_rejects_empty_title(mcp_docs):
    with pytest.raises(ValueError, match="title"):
        await _call(mcp_docs, "capture_document", {"title": " ", "kind": "note"})


async def test_capture_document_rejects_empty_kind(mcp_docs):
    with pytest.raises(ValueError, match="kind"):
        await _call(mcp_docs, "capture_document", {"title": "t", "kind": ""})


# ──────────────────────────────────────────────────────────────────
# add_chunks
# ──────────────────────────────────────────────────────────────────

async def test_add_chunks_inserts_with_embeddings(mcp_docs, monkeypatch):
    _stub_openrouter(monkeypatch, [0.4] * 1536)
    doc = await _call(mcp_docs, "capture_document", {
        "title": "Chunk parent", "kind": "article", "content_md": "seed",
    })
    result = await _call(mcp_docs, "add_chunks", {
        "document_id": doc["id"],
        "chunks": [
            {"chunk_index": 0, "content": "chunk zero"},
            {"chunk_index": 1, "content": "chunk one", "metadata": {"page": 1}},
        ],
    })
    assert result["inserted"] == 2
    assert result["updated"] == 0
    assert result["total"] == 2


async def test_add_chunks_is_idempotent_on_chunk_index(mcp_docs, monkeypatch):
    _stub_openrouter(monkeypatch, [0.5] * 1536)
    doc = await _call(mcp_docs, "capture_document", {
        "title": "Re-chunk", "kind": "article", "content_md": "seed",
    })
    await _call(mcp_docs, "add_chunks", {
        "document_id": doc["id"],
        "chunks": [{"chunk_index": 0, "content": "first cut"}],
    })
    re_run = await _call(mcp_docs, "add_chunks", {
        "document_id": doc["id"],
        "chunks": [{"chunk_index": 0, "content": "second cut"}],
    })
    assert re_run["inserted"] == 0
    assert re_run["updated"] == 1

    async with db.conn() as connection:
        row = await connection.fetchrow(
            "SELECT content FROM chunks WHERE document_id = $1::uuid AND chunk_index = 0",
            doc["id"],
        )
    assert row["content"] == "second cut"


async def test_add_chunks_rejects_missing_document(mcp_docs):
    with pytest.raises(ValueError, match="does not exist"):
        await _call(mcp_docs, "add_chunks", {
            "document_id": "00000000-0000-0000-0000-000000000000",
            "chunks": [{"chunk_index": 0, "content": "orphan"}],
        })


async def test_add_chunks_validates_chunk_shape(mcp_docs, monkeypatch):
    _stub_openrouter(monkeypatch, [0.6] * 1536)
    doc = await _call(mcp_docs, "capture_document", {
        "title": "Validation parent", "kind": "article", "content_md": "seed",
    })
    with pytest.raises(ValueError, match="chunk_index"):
        await _call(mcp_docs, "add_chunks", {
            "document_id": doc["id"],
            "chunks": [{"content": "missing index"}],
        })
    with pytest.raises(ValueError, match="content"):
        await _call(mcp_docs, "add_chunks", {
            "document_id": doc["id"],
            "chunks": [{"chunk_index": 0}],
        })
    with pytest.raises(ValueError, match="non-empty"):
        await _call(mcp_docs, "add_chunks", {
            "document_id": doc["id"],
            "chunks": [{"chunk_index": 0, "content": "   "}],
        })


# ──────────────────────────────────────────────────────────────────
# search_chunks
# ──────────────────────────────────────────────────────────────────

async def test_search_chunks_round_trips(mcp_docs, monkeypatch):
    _stub_openrouter(monkeypatch, [0.7] * 1536)
    doc = await _call(mcp_docs, "capture_document", {
        "title": "Searchable doc", "kind": "article",
        "source": "https://example.com/s", "content_md": "seed",
    })
    await _call(mcp_docs, "add_chunks", {
        "document_id": doc["id"],
        "chunks": [{"chunk_index": 0, "content": "needle in passage"}],
    })
    results = await _call(mcp_docs, "search_chunks", {"query": "needle in passage"})
    assert results
    top = results[0]
    assert top["content"] == "needle in passage"
    assert top["document_title"] == "Searchable doc"
    assert top["document_source"] == "https://example.com/s"
    assert top["similarity"] == pytest.approx(1.0, abs=1e-6)


async def test_search_chunks_filters_by_document(mcp_docs, monkeypatch):
    _stub_openrouter(monkeypatch, [0.8] * 1536)
    doc_a = await _call(mcp_docs, "capture_document", {
        "title": "A", "kind": "article", "content_md": "seed-a",
    })
    doc_b = await _call(mcp_docs, "capture_document", {
        "title": "B", "kind": "article", "content_md": "seed-b",
    })
    await _call(mcp_docs, "add_chunks", {
        "document_id": doc_a["id"],
        "chunks": [{"chunk_index": 0, "content": "in A"}],
    })
    await _call(mcp_docs, "add_chunks", {
        "document_id": doc_b["id"],
        "chunks": [{"chunk_index": 0, "content": "in B"}],
    })

    results = await _call(mcp_docs, "search_chunks", {
        "query": "looking",
        "document_id": doc_a["id"],
    })
    contents = {r["content"] for r in results}
    assert "in A" in contents
    assert "in B" not in contents


async def test_search_chunks_filters_by_project(mcp_docs, monkeypatch):
    _stub_openrouter(monkeypatch, [0.9] * 1536)
    ax = await _call(mcp_docs, "capture_document", {
        "title": "Ax doc", "kind": "article", "content_md": "seed-ax",
        "project": "ax",
    })
    other = await _call(mcp_docs, "capture_document", {
        "title": "Other doc", "kind": "article", "content_md": "seed-other",
        "project": "other",
    })
    await _call(mcp_docs, "add_chunks", {
        "document_id": ax["id"],
        "chunks": [{"chunk_index": 0, "content": "ax passage"}],
    })
    await _call(mcp_docs, "add_chunks", {
        "document_id": other["id"],
        "chunks": [{"chunk_index": 0, "content": "other passage"}],
    })

    results = await _call(mcp_docs, "search_chunks", {
        "query": "passage",
        "project": "ax",
    })
    contents = {r["content"] for r in results}
    assert "ax passage" in contents
    assert "other passage" not in contents


async def test_search_chunks_validates_arguments(mcp_docs):
    with pytest.raises(ValueError, match="non-empty"):
        await _call(mcp_docs, "search_chunks", {"query": ""})
    with pytest.raises(ValueError, match="match_count"):
        await _call(mcp_docs, "search_chunks", {"query": "x", "match_count": 0})
    with pytest.raises(ValueError, match="match_threshold"):
        await _call(mcp_docs, "search_chunks", {"query": "x", "match_threshold": -0.1})
