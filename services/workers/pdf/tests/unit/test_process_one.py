"""Unit tests for worker_pdf.worker.process_one.

Inject a fake extractor + stub MCP so the test never needs Docling
or a real PDF. Tests cover: payload validation, fetch failure
fallthrough, extractor failure fallthrough, happy path with
verified call shape, duplicate-skip behaviour, project propagation,
temp-file cleanup.

Layer: unit
Phase: 12.c
Run:   pytest services/workers/pdf/tests/unit/test_process_one.py -v
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from worker_pdf.config import Config
from worker_pdf.extractor import ExtractedDocument
from worker_pdf.worker import process_one


def _cfg(*, max_pdf_bytes: int = 20 * 1024 * 1024) -> Config:
    return Config(
        enabled=True,
        brain_url="http://mcp/mcp?key=k",
        redis_url="redis://redis:6379/0",
        queue="ingest:pdf",
        max_pdf_bytes=max_pdf_bytes,
        max_chunk_tokens=200,
        chunk_overlap_tokens=40,
    )


class _StubMcp:
    def __init__(self, *, duplicate: bool = False) -> None:
        self.captures: list[dict[str, Any]] = []
        self.chunk_batches: list[list[dict[str, Any]]] = []
        self._duplicate = duplicate
        self._doc_id = "doc-pdf-1234"

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
        return {"document_id": document_id, "inserted": len(chunks)}


class _StubExtractor:
    def __init__(self, *, doc: ExtractedDocument | None = None, raises: Exception | None = None) -> None:
        self._doc = doc
        self._raises = raises
        self.calls: list[Path] = []

    def extract(self, path: Path) -> ExtractedDocument:
        self.calls.append(path)
        if self._raises:
            raise self._raises
        assert self._doc is not None
        return self._doc


def _make_doc(markdown: str = "para a\n\npara b\n\npara c") -> ExtractedDocument:
    return ExtractedDocument(
        title="Test PDF",
        markdown=markdown,
        sha256="a" * 64,
        page_count=3,
    )


# ──────────────────────────────────────────────────────────────────
# Payload validation
# ──────────────────────────────────────────────────────────────────

async def test_job_without_path_or_url_is_skipped(tmp_path):
    mcp = _StubMcp()
    outcome = await process_one(
        {"note": "nothing to fetch"},
        config=_cfg(),
        mcp=mcp,
        extractor=_StubExtractor(doc=_make_doc()),
    )
    assert outcome == {"status": "skip", "reason": "no path or url"}
    assert mcp.captures == []


# ──────────────────────────────────────────────────────────────────
# Fetch failure surfaces as skip
# ──────────────────────────────────────────────────────────────────

async def test_missing_local_path_is_skipped(tmp_path):
    mcp = _StubMcp()
    outcome = await process_one(
        {"path": str(tmp_path / "no-such.pdf")},
        config=_cfg(),
        mcp=mcp,
        extractor=_StubExtractor(doc=_make_doc()),
    )
    assert outcome["status"] == "skip"
    assert "fetch failed" in outcome["reason"]
    assert mcp.captures == []


async def test_oversized_local_pdf_is_skipped(tmp_path):
    pdf = tmp_path / "big.pdf"
    pdf.write_bytes(b"x" * 2048)
    mcp = _StubMcp()
    outcome = await process_one(
        {"path": str(pdf)},
        config=_cfg(max_pdf_bytes=1024),
        mcp=mcp,
        extractor=_StubExtractor(doc=_make_doc()),
    )
    assert outcome["status"] == "skip"
    assert mcp.captures == []


# ──────────────────────────────────────────────────────────────────
# Extractor failure
# ──────────────────────────────────────────────────────────────────

async def test_extractor_failure_returns_skip(tmp_path):
    pdf = tmp_path / "good.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    mcp = _StubMcp()
    outcome = await process_one(
        {"path": str(pdf)},
        config=_cfg(),
        mcp=mcp,
        extractor=_StubExtractor(raises=RuntimeError("docling exploded")),
    )
    assert outcome["status"] == "skip"
    assert "extract failed" in outcome["reason"]
    assert mcp.captures == []


# ──────────────────────────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────────────────────────

async def test_happy_path_captures_and_chunks(tmp_path):
    pdf = tmp_path / "report.pdf"
    pdf.write_bytes(b"%PDF-1.4 body")
    doc = _make_doc(
        markdown="\n\n".join(f"section {i}" * 50 for i in range(10))
    )
    mcp = _StubMcp()
    extractor = _StubExtractor(doc=doc)

    outcome = await process_one(
        {
            "path": str(pdf),
            "title": "Overridden Title",
            "note": "via local upload",
            "message_id": 42,
            "project": "ax",
        },
        config=_cfg(),
        mcp=mcp,
        extractor=extractor,
        chunk_batch_size=3,
    )

    assert outcome["status"] == "ingested"
    assert outcome["document_id"] == "doc-pdf-1234"
    assert outcome["page_count"] == 3
    assert outcome["chunks"] >= 2
    assert outcome["inserted"] == outcome["chunks"]

    assert extractor.calls == [pdf]
    cap = mcp.captures[0]
    assert cap["kind"] == "pdf"
    assert cap["title"] == "Overridden Title"  # job override wins over extractor
    assert cap["source"] == str(pdf)
    assert cap["sha256"] == doc.sha256
    assert cap["project"] == "ax"
    assert cap["metadata"]["page_count"] == 3
    assert cap["metadata"]["note"] == "via local upload"
    assert cap["metadata"]["message_id"] == 42

    # Batch size enforced.
    for batch in mcp.chunk_batches:
        assert 1 <= len(batch) <= 3


async def test_title_defaults_to_extractor_title_when_job_has_none(tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    mcp = _StubMcp()
    await process_one(
        {"path": str(pdf)},
        config=_cfg(),
        mcp=mcp,
        extractor=_StubExtractor(doc=_make_doc()),
    )
    assert mcp.captures[0]["title"] == "Test PDF"


async def test_no_project_kwarg_when_absent(tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    mcp = _StubMcp()
    await process_one(
        {"path": str(pdf)},
        config=_cfg(),
        mcp=mcp,
        extractor=_StubExtractor(doc=_make_doc()),
    )
    assert "project" not in mcp.captures[0]


# ──────────────────────────────────────────────────────────────────
# Duplicate handling
# ──────────────────────────────────────────────────────────────────

async def test_duplicate_skips_add_chunks(tmp_path):
    pdf = tmp_path / "seen.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    mcp = _StubMcp(duplicate=True)
    outcome = await process_one(
        {"path": str(pdf)},
        config=_cfg(),
        mcp=mcp,
        extractor=_StubExtractor(doc=_make_doc()),
    )
    assert outcome["status"] == "duplicate"
    assert mcp.chunk_batches == []


# ──────────────────────────────────────────────────────────────────
# URL mode + temp file cleanup
# ──────────────────────────────────────────────────────────────────

async def test_url_mode_cleans_up_temp_file(tmp_path, monkeypatch):
    """When the fetcher writes a temp file (owned=True), process_one
    must delete it after the job — success or skip. Use a fake
    fetcher that records the produced path so we can confirm it was
    cleaned up."""
    import worker_pdf.worker as worker_mod

    fake_path = tmp_path / "owned-temp.pdf"
    fake_path.write_bytes(b"%PDF-1.4 owned")

    async def fake_fetch(job, *, max_bytes, **kw):
        return fake_path, True

    monkeypatch.setattr(worker_mod, "fetch_pdf", fake_fetch)

    mcp = _StubMcp()
    await process_one(
        {"url": "https://example.com/x.pdf"},
        config=_cfg(),
        mcp=mcp,
        extractor=_StubExtractor(doc=_make_doc()),
    )
    assert not fake_path.exists(), "owned temp file should have been deleted"
