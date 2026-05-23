"""Unit tests for worker_article.worker.process_one.

The worker loop is broken out into a pure-ish process_one() that
takes injected MCP and fetcher dependencies. These tests verify the
contract:

- Skips when the URL is missing.
- Skips when the fetcher returns None (extraction failed).
- Calls capture_document with the right fields.
- Skips add_chunks when capture_document reports duplicate=true.
- Calls add_chunks in batches of `chunk_batch_size`.
- Returns a status dict.

Layer: unit
Phase: 12.b
Run:   pytest services/workers/article/tests/unit/test_process_one.py -v
"""
from __future__ import annotations

from typing import Any

import pytest

from worker_article.config import Config
from worker_article.fetcher import ExtractedArticle
from worker_article.worker import process_one


def _cfg() -> Config:
    return Config(
        enabled=True,
        brain_url="http://mcp/mcp?key=k",
        redis_url="redis://redis:6379/0",
        queue="ingest:article",
        max_chunk_tokens=200,
        chunk_overlap_tokens=40,
    )


class _StubMcp:
    def __init__(self, *, duplicate: bool = False) -> None:
        self.captures: list[dict[str, Any]] = []
        self.chunk_batches: list[list[dict[str, Any]]] = []
        self._duplicate = duplicate
        self._doc_id = "doc-1234"

    async def capture_document(self, **kw) -> dict[str, Any]:
        self.captures.append(kw)
        return {
            "id": self._doc_id,
            "sha256": kw["sha256"],
            "duplicate": self._duplicate,
            "embedded": True,
        }

    async def add_chunks(self, *, document_id: str, chunks: list[dict[str, Any]]) -> dict[str, Any]:
        self.chunk_batches.append(chunks)
        return {
            "document_id": document_id,
            "inserted": len(chunks),
            "updated": 0,
            "total": sum(len(b) for b in self.chunk_batches),
        }


def _make_fetcher(article: ExtractedArticle | None):
    async def _fetcher(url: str, **kw) -> ExtractedArticle | None:
        return article

    return _fetcher


# ──────────────────────────────────────────────────────────────────
# Job validation
# ──────────────────────────────────────────────────────────────────

async def test_job_without_url_is_skipped():
    mcp = _StubMcp()
    outcome = await process_one(
        {"note": "no url here"},
        config=_cfg(),
        mcp=mcp,
        fetcher=_make_fetcher(None),
    )
    assert outcome == {"status": "skip", "reason": "no url"}
    assert mcp.captures == []
    assert mcp.chunk_batches == []


# ──────────────────────────────────────────────────────────────────
# Fetcher failure
# ──────────────────────────────────────────────────────────────────

async def test_fetcher_returning_none_skips_cleanly():
    mcp = _StubMcp()
    outcome = await process_one(
        {"url": "https://example.com/x"},
        config=_cfg(),
        mcp=mcp,
        fetcher=_make_fetcher(None),
    )
    assert outcome["status"] == "skip"
    assert outcome["reason"] == "extract failed"
    assert outcome["url"] == "https://example.com/x"
    assert mcp.captures == []
    assert mcp.chunk_batches == []


# ──────────────────────────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────────────────────────

async def test_capture_then_add_chunks_for_new_article():
    article = ExtractedArticle(
        url="https://example.com/post",
        title="Example post",
        markdown="\n\n".join([f"para {i} " * 30 for i in range(20)]),
        sha256="a" * 64,
    )
    mcp = _StubMcp(duplicate=False)
    outcome = await process_one(
        {"url": article.url, "note": "forwarded from telegram", "message_id": 99},
        config=_cfg(),
        mcp=mcp,
        fetcher=_make_fetcher(article),
        chunk_batch_size=4,
    )

    assert outcome["status"] == "ingested"
    assert outcome["document_id"] == "doc-1234"
    assert outcome["chunks"] >= 2
    assert outcome["inserted"] == outcome["chunks"]

    assert len(mcp.captures) == 1
    cap = mcp.captures[0]
    assert cap["title"] == "Example post"
    assert cap["kind"] == "article"
    assert cap["source"] == article.url
    assert cap["sha256"] == article.sha256
    assert cap["metadata"]["note"] == "forwarded from telegram"
    assert cap["metadata"]["message_id"] == 99

    # Verify batching: every batch must have at most chunk_batch_size items.
    for batch in mcp.chunk_batches:
        assert 1 <= len(batch) <= 4


async def test_duplicate_document_skips_add_chunks():
    article = ExtractedArticle(
        url="https://example.com/x",
        title="seen before",
        markdown="something already in the brain " * 200,
        sha256="b" * 64,
    )
    mcp = _StubMcp(duplicate=True)
    outcome = await process_one(
        {"url": article.url},
        config=_cfg(),
        mcp=mcp,
        fetcher=_make_fetcher(article),
    )
    assert outcome == {
        "status": "duplicate",
        "url": "https://example.com/x",
        "document_id": "doc-1234",
    }
    assert len(mcp.captures) == 1
    assert mcp.chunk_batches == [], "duplicates must not re-chunk"


# ──────────────────────────────────────────────────────────────────
# Project tag passthrough
# ──────────────────────────────────────────────────────────────────

async def test_project_tag_propagates_to_capture():
    article = ExtractedArticle(
        url="https://example.com/p",
        title="x",
        markdown="body " * 200,
        sha256="c" * 64,
    )
    mcp = _StubMcp()
    await process_one(
        {"url": article.url, "project": "ax"},
        config=_cfg(),
        mcp=mcp,
        fetcher=_make_fetcher(article),
    )
    assert mcp.captures[0]["project"] == "ax"


async def test_no_project_tag_when_absent():
    article = ExtractedArticle(
        url="https://example.com/p",
        title="x",
        markdown="body " * 200,
        sha256="d" * 64,
    )
    mcp = _StubMcp()
    await process_one(
        {"url": article.url},
        config=_cfg(),
        mcp=mcp,
        fetcher=_make_fetcher(article),
    )
    assert "project" not in mcp.captures[0]
