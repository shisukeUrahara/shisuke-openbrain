"""Audio -> transcript via faster-whisper.

Hidden behind a Protocol so tests inject a trivial fake without
loading faster-whisper or its CTranslate2 backend. The default
WhisperTranscriber loads the model lazily on first .transcribe()
call — keeps test collection and idle mode light.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol


logger = logging.getLogger("worker_audio.transcriber")


@dataclass(frozen=True)
class Transcript:
    title: str
    markdown: str
    sha256: str
    language: str | None = None
    duration_s: float | None = None
    segment_count: int | None = None
    segments: list[dict] = field(default_factory=list)


class AudioTranscriber(Protocol):
    def transcribe(self, path: Path, *, title_fallback: str) -> Transcript: ...


class WhisperTranscriber:
    """faster-whisper-backed transcriber.

    The model is loaded once per process (lazy). Calling
    .transcribe() multiple times reuses the same model.
    """

    def __init__(self, *, model_name: str = "small", compute_type: str = "int8") -> None:
        self._model_name = model_name
        self._compute_type = compute_type
        self._model = None

    def transcribe(self, path: Path, *, title_fallback: str) -> Transcript:
        from faster_whisper import WhisperModel  # local import (heavy)

        if self._model is None:
            logger.info(
                "loading faster-whisper model=%s compute_type=%s",
                self._model_name,
                self._compute_type,
            )
            self._model = WhisperModel(
                self._model_name,
                device="cpu",
                compute_type=self._compute_type,
            )

        segments_iter, info = self._model.transcribe(
            str(path),
            language=None,
            vad_filter=True,
            beam_size=5,
        )

        segments_list: list[dict] = []
        for s in segments_iter:
            segments_list.append({
                "start": float(s.start),
                "end": float(s.end),
                "text": s.text.strip(),
            })

        markdown = _segments_to_markdown(segments_list)
        sha = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        return Transcript(
            title=title_fallback,
            markdown=markdown,
            sha256=sha,
            language=getattr(info, "language", None),
            duration_s=float(getattr(info, "duration", 0.0)) or None,
            segment_count=len(segments_list),
            segments=segments_list,
        )


def _segments_to_markdown(segments: list[dict]) -> str:
    """Render whisper segments as paragraph-separated markdown.

    Group consecutive segments into paragraphs whenever there is a
    gap of > 1.5 seconds between them, with a hard cap of 6 segments
    per paragraph so very fast speakers do not produce wall-of-text.
    Blank-line separators are what the chunker needs.
    """
    if not segments:
        return ""

    paragraphs: list[list[str]] = []
    current: list[str] = []
    last_end = segments[0]["start"]

    for seg in segments:
        gap = seg["start"] - last_end
        if (gap > 1.5 or len(current) >= 6) and current:
            paragraphs.append(current)
            current = []
        current.append(seg["text"])
        last_end = seg["end"]
    if current:
        paragraphs.append(current)

    return "\n\n".join(" ".join(p).strip() for p in paragraphs).strip()
