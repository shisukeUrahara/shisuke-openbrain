"""Unit tests for worker_audio.transcriber._segments_to_markdown.

The Whisper-backed transcriber depends on faster-whisper which is
~200 MB of CTranslate2 binaries. We test the pure rendering helper
that turns a segment list into chunker-ready markdown. The
WhisperTranscriber class is covered in the integration suite (live
ingestion) since exercising it requires the model.

Layer: unit
Phase: 12.d
Run:   pytest services/workers/audio/tests/unit/test_transcriber.py -v
"""
from __future__ import annotations

import pytest

from worker_audio.transcriber import _segments_to_markdown


def _seg(start: float, end: float, text: str) -> dict:
    return {"start": start, "end": end, "text": text}


def test_empty_segments_yields_empty_string():
    assert _segments_to_markdown([]) == ""


def test_single_segment_becomes_single_paragraph():
    md = _segments_to_markdown([_seg(0.0, 1.5, "hello world")])
    assert md == "hello world"


def test_consecutive_segments_with_short_gaps_stay_together():
    """Gaps under 1.5 s should keep speakers in the same paragraph."""
    segments = [
        _seg(0.0, 1.0, "first thought"),
        _seg(1.2, 2.5, "still speaking"),
        _seg(2.8, 3.6, "wrapping up"),
    ]
    md = _segments_to_markdown(segments)
    assert "\n\n" not in md
    assert "first thought" in md
    assert "wrapping up" in md


def test_long_gap_creates_paragraph_break():
    """A pause >= 1.5s splits the paragraph."""
    segments = [
        _seg(0.0, 1.0, "before pause"),
        _seg(5.0, 6.0, "after pause"),
    ]
    md = _segments_to_markdown(segments)
    paragraphs = md.split("\n\n")
    assert len(paragraphs) == 2
    assert "before pause" in paragraphs[0]
    assert "after pause" in paragraphs[1]


def test_segment_run_caps_at_six_to_avoid_wall_of_text():
    """Even with no pause, accumulating > 6 segments forces a break."""
    segments = [_seg(i * 0.5, (i * 0.5) + 0.4, f"seg{i}") for i in range(15)]
    md = _segments_to_markdown(segments)
    paragraphs = md.split("\n\n")
    # 15 segments / 6 per paragraph = at least 3 paragraphs.
    assert len(paragraphs) >= 3


def test_text_is_stripped_per_segment():
    segments = [_seg(0.0, 1.0, "   hello   ")]
    md = _segments_to_markdown(segments)
    assert md == "hello"


def test_paragraphs_join_segments_with_spaces():
    segments = [
        _seg(0.0, 1.0, "alpha"),
        _seg(1.1, 2.0, "beta"),
    ]
    md = _segments_to_markdown(segments)
    assert md == "alpha beta"
