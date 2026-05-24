"""Unit tests for worker_image.worker.process_one.

Inject a stub analyzer + stub MCP so the test never needs an
OpenRouter key or a real image.

Layer: unit
Phase: 12.e
Run:   pytest services/workers/image/tests/unit/test_process_one.py -v
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from worker_image.analyzer import AnalysisError, AnalyzedImage
from worker_image.config import Config
from worker_image.worker import process_one


def _cfg() -> Config:
    return Config(
        enabled=True,
        brain_url="http://mcp/mcp?key=k",
        redis_url="redis://redis:6379/0",
        queue="ingest:image",
        openrouter_api_key="sk-test",
        vision_model="qwen/qwen-2.5-vl-7b-instruct",
        max_image_bytes=10 * 1024 * 1024,
        max_chunk_tokens=200,
        chunk_overlap_tokens=40,
    )


class _StubMcp:
    def __init__(self, *, duplicate: bool = False) -> None:
        self.captures: list[dict[str, Any]] = []
        self.chunk_batches: list[list[dict[str, Any]]] = []
        self._duplicate = duplicate
        self._doc_id = "doc-image-1"

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


class _StubAnalyzer:
    def __init__(self, *, analyzed: AnalyzedImage | None = None, raises: Exception | None = None) -> None:
        self._analyzed = analyzed
        self._raises = raises
        self.calls: list[dict] = []

    async def analyze(self, *, image_bytes: bytes, mime: str, caption: str | None) -> AnalyzedImage:
        self.calls.append({"size": len(image_bytes), "mime": mime, "caption": caption})
        if self._raises:
            raise self._raises
        assert self._analyzed is not None
        return self._analyzed


def _result(markdown: str = "## Extracted Text\nHELLO\n\n## Description\nA poster that reads HELLO.") -> AnalyzedImage:
    return AnalyzedImage(title="HELLO poster", markdown=markdown, sha256="a" * 64)


# ──────────────────────────────────────────────────────────────────
# Payload validation
# ──────────────────────────────────────────────────────────────────

async def test_job_with_no_inputs_is_skipped(tmp_path):
    mcp = _StubMcp()
    outcome = await process_one(
        {"note": "no source"},
        config=_cfg(),
        mcp=mcp,
        analyzer=_StubAnalyzer(analyzed=_result()),
    )
    assert outcome == {"status": "skip", "reason": "no url/path/file_id"}


# ──────────────────────────────────────────────────────────────────
# Fetcher / analyzer failures
# ──────────────────────────────────────────────────────────────────

async def test_missing_local_file_is_skipped(tmp_path):
    mcp = _StubMcp()
    outcome = await process_one(
        {"path": str(tmp_path / "no-such.jpg")},
        config=_cfg(),
        mcp=mcp,
        analyzer=_StubAnalyzer(analyzed=_result()),
    )
    assert outcome["status"] == "skip"
    assert "fetch failed" in outcome["reason"]


async def test_telegram_file_id_skipped_cleanly(tmp_path):
    mcp = _StubMcp()
    outcome = await process_one(
        {"file_id": "abc"},
        config=_cfg(),
        mcp=mcp,
        analyzer=_StubAnalyzer(analyzed=_result()),
    )
    assert outcome["status"] == "skip"
    assert "not yet supported" in outcome["reason"]


async def test_analyzer_failure_returns_skip(tmp_path):
    img = tmp_path / "x.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    mcp = _StubMcp()
    outcome = await process_one(
        {"path": str(img)},
        config=_cfg(),
        mcp=mcp,
        analyzer=_StubAnalyzer(raises=AnalysisError("upstream down")),
    )
    assert outcome["status"] == "skip"
    assert "analysis failed" in outcome["reason"]


# ──────────────────────────────────────────────────────────────────
# Happy path
# ──────────────────────────────────────────────────────────────────

async def test_happy_path_captures_and_chunks(tmp_path):
    img = tmp_path / "receipt.jpg"
    img.write_bytes(b"\xff\xd8\xff" + b"jpegbody" * 8)
    analyzed = _result(
        markdown="\n\n".join(f"section {i}" * 40 for i in range(5))
    )
    mcp = _StubMcp()
    analyzer = _StubAnalyzer(analyzed=analyzed)

    outcome = await process_one(
        {
            "path": str(img),
            "caption": "lunch receipt",
            "project": "ax",
            "note": "via telegram fwd",
            "message_id": 99,
        },
        config=_cfg(),
        mcp=mcp,
        analyzer=analyzer,
        chunk_batch_size=2,
    )

    assert outcome["status"] == "ingested"
    assert outcome["chunks"] >= 2
    assert outcome["inserted"] == outcome["chunks"]

    # Analyzer was called with caption + the file's bytes + the
    # correct mime.
    assert len(analyzer.calls) == 1
    call = analyzer.calls[0]
    assert call["caption"] == "lunch receipt"
    assert call["mime"] == "image/jpeg"
    assert call["size"] == img.stat().st_size

    cap = mcp.captures[0]
    assert cap["kind"] == "image"
    assert cap["source"] == str(img)
    assert cap["project"] == "ax"
    assert cap["metadata"]["caption"] == "lunch receipt"
    assert cap["metadata"]["mime"] == "image/jpeg"
    assert cap["metadata"]["note"] == "via telegram fwd"
    assert cap["metadata"]["message_id"] == 99

    # Batching enforced.
    for batch in mcp.chunk_batches:
        assert 1 <= len(batch) <= 2


async def test_no_project_kwarg_when_absent(tmp_path):
    img = tmp_path / "x.png"
    img.write_bytes(b"data")
    mcp = _StubMcp()
    await process_one(
        {"path": str(img)},
        config=_cfg(),
        mcp=mcp,
        analyzer=_StubAnalyzer(analyzed=_result()),
    )
    assert "project" not in mcp.captures[0]


# ──────────────────────────────────────────────────────────────────
# Duplicate handling
# ──────────────────────────────────────────────────────────────────

async def test_duplicate_image_skips_add_chunks(tmp_path):
    img = tmp_path / "seen.jpg"
    img.write_bytes(b"\xff\xd8\xff jpeg")
    mcp = _StubMcp(duplicate=True)
    outcome = await process_one(
        {"path": str(img)},
        config=_cfg(),
        mcp=mcp,
        analyzer=_StubAnalyzer(analyzed=_result()),
    )
    assert outcome["status"] == "duplicate"
    assert mcp.chunk_batches == []
