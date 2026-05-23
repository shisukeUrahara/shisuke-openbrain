"""Unit tests for worker_audio.worker.process_one.

Inject a fake transcriber and stub MCP so the test never needs
faster-whisper or a real audio file.

Layer: unit
Phase: 12.d
Run:   pytest services/workers/audio/tests/unit/test_process_one.py -v
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from worker_audio.config import Config
from worker_audio.transcriber import Transcript
from worker_audio.worker import process_one


def _cfg(*, max_audio_bytes: int = 200 * 1024 * 1024) -> Config:
    return Config(
        enabled=True,
        brain_url="http://mcp/mcp?key=k",
        redis_url="redis://redis:6379/0",
        queue_voice="ingest:voice",
        queue_youtube="ingest:youtube",
        whisper_model="small",
        whisper_compute_type="int8",
        max_audio_bytes=max_audio_bytes,
        max_chunk_tokens=200,
        chunk_overlap_tokens=40,
    )


class _StubMcp:
    def __init__(self, *, duplicate: bool = False) -> None:
        self.captures: list[dict[str, Any]] = []
        self.chunk_batches: list[list[dict[str, Any]]] = []
        self._duplicate = duplicate
        self._doc_id = "doc-audio-1234"

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


class _StubTranscriber:
    def __init__(self, *, transcript: Transcript | None = None, raises: Exception | None = None) -> None:
        self._transcript = transcript
        self._raises = raises
        self.calls: list[Path] = []

    def transcribe(self, path: Path, *, title_fallback: str) -> Transcript:
        self.calls.append(path)
        if self._raises:
            raise self._raises
        assert self._transcript is not None
        return self._transcript


def _make_transcript(markdown: str = "para a\n\npara b\n\npara c") -> Transcript:
    return Transcript(
        title="Test clip",
        markdown=markdown,
        sha256="a" * 64,
        language="en",
        duration_s=42.0,
        segment_count=3,
        segments=[],
    )


# ──────────────────────────────────────────────────────────────────
# Payload validation
# ──────────────────────────────────────────────────────────────────

async def test_job_with_no_inputs_is_skipped(tmp_path):
    mcp = _StubMcp()
    outcome = await process_one(
        {"note": "nothing"},
        config=_cfg(),
        mcp=mcp,
        transcriber=_StubTranscriber(transcript=_make_transcript()),
        queue_name="ingest:voice",
    )
    assert outcome == {"status": "skip", "reason": "no url/path/file_id"}


# ──────────────────────────────────────────────────────────────────
# Fetch failure surfaces as skip
# ──────────────────────────────────────────────────────────────────

async def test_missing_local_audio_is_skipped(tmp_path):
    mcp = _StubMcp()
    outcome = await process_one(
        {"path": str(tmp_path / "no-such.ogg")},
        config=_cfg(),
        mcp=mcp,
        transcriber=_StubTranscriber(transcript=_make_transcript()),
        queue_name="ingest:voice",
    )
    assert outcome["status"] == "skip"
    assert "fetch failed" in outcome["reason"]


async def test_telegram_file_id_is_skipped_until_token_wired(tmp_path):
    """Telegram voice notes get classified by the bot but the worker
    cannot download them yet. Confirm the skip path is clean rather
    than a crash."""
    mcp = _StubMcp()
    outcome = await process_one(
        {"file_id": "abcd", "duration_s": 7},
        config=_cfg(),
        mcp=mcp,
        transcriber=_StubTranscriber(transcript=_make_transcript()),
        queue_name="ingest:voice",
    )
    assert outcome["status"] == "skip"
    assert "not yet supported" in outcome["reason"]


# ──────────────────────────────────────────────────────────────────
# Transcriber failure
# ──────────────────────────────────────────────────────────────────

async def test_transcriber_failure_returns_skip(tmp_path):
    clip = tmp_path / "broken.ogg"
    clip.write_bytes(b"OGGS")
    mcp = _StubMcp()
    outcome = await process_one(
        {"path": str(clip)},
        config=_cfg(),
        mcp=mcp,
        transcriber=_StubTranscriber(raises=RuntimeError("whisper crashed")),
        queue_name="ingest:voice",
    )
    assert outcome["status"] == "skip"
    assert "transcribe failed" in outcome["reason"]


async def test_empty_transcript_is_skipped(tmp_path):
    """A silent audio file may transcribe to nothing. Skip rather
    than write an empty document."""
    clip = tmp_path / "silence.ogg"
    clip.write_bytes(b"OGGS")
    mcp = _StubMcp()
    outcome = await process_one(
        {"path": str(clip)},
        config=_cfg(),
        mcp=mcp,
        transcriber=_StubTranscriber(transcript=_make_transcript(markdown="   ")),
        queue_name="ingest:voice",
    )
    assert outcome["status"] == "skip"
    assert "empty transcript" in outcome["reason"]


# ──────────────────────────────────────────────────────────────────
# Happy paths — voice vs youtube
# ──────────────────────────────────────────────────────────────────

async def test_voice_queue_captures_with_kind_voice(tmp_path):
    clip = tmp_path / "note.ogg"
    clip.write_bytes(b"OGGS")
    transcript = _make_transcript(
        markdown="\n\n".join(f"section {i}" * 50 for i in range(8))
    )
    mcp = _StubMcp()
    outcome = await process_one(
        {"path": str(clip), "title": "voice note", "project": "ax"},
        config=_cfg(),
        mcp=mcp,
        transcriber=_StubTranscriber(transcript=transcript),
        queue_name="ingest:voice",
        chunk_batch_size=3,
    )
    assert outcome["status"] == "ingested"
    assert outcome["kind"] == "voice"
    assert mcp.captures[0]["kind"] == "voice"
    assert mcp.captures[0]["title"] == "voice note"
    assert mcp.captures[0]["project"] == "ax"
    assert mcp.captures[0]["metadata"]["language"] == "en"
    assert mcp.captures[0]["metadata"]["duration_s"] == 42.0

    # Batching enforced.
    for batch in mcp.chunk_batches:
        assert 1 <= len(batch) <= 3


async def test_youtube_queue_captures_with_kind_youtube(tmp_path):
    clip = tmp_path / "yt.mp3"
    clip.write_bytes(b"MP3FAKE")
    mcp = _StubMcp()
    outcome = await process_one(
        {"path": str(clip)},
        config=_cfg(),
        mcp=mcp,
        transcriber=_StubTranscriber(transcript=_make_transcript()),
        queue_name="ingest:youtube",
    )
    assert outcome["status"] == "ingested"
    assert outcome["kind"] == "youtube"
    assert mcp.captures[0]["kind"] == "youtube"


# ──────────────────────────────────────────────────────────────────
# Duplicate handling
# ──────────────────────────────────────────────────────────────────

async def test_duplicate_audio_skips_add_chunks(tmp_path):
    clip = tmp_path / "seen.ogg"
    clip.write_bytes(b"OGGS")
    mcp = _StubMcp(duplicate=True)
    outcome = await process_one(
        {"path": str(clip)},
        config=_cfg(),
        mcp=mcp,
        transcriber=_StubTranscriber(transcript=_make_transcript()),
        queue_name="ingest:voice",
    )
    assert outcome["status"] == "duplicate"
    assert mcp.chunk_batches == []


# ──────────────────────────────────────────────────────────────────
# project absence
# ──────────────────────────────────────────────────────────────────

async def test_no_project_kwarg_when_absent(tmp_path):
    clip = tmp_path / "x.ogg"
    clip.write_bytes(b"OGGS")
    mcp = _StubMcp()
    await process_one(
        {"path": str(clip)},
        config=_cfg(),
        mcp=mcp,
        transcriber=_StubTranscriber(transcript=_make_transcript()),
        queue_name="ingest:voice",
    )
    assert "project" not in mcp.captures[0]
