"""Unit tests for worker_article.chunker.

The chunker is pure — known input, known output. These tests are the
contract for how article markdown becomes chunks.

Layer: unit
Phase: 12.b
Run:   pytest services/workers/article/tests/unit/test_chunker.py -v
"""
from __future__ import annotations

import pytest

from worker_article.chunker import chunk_markdown


# ──────────────────────────────────────────────────────────────────
# Boundary cases
# ──────────────────────────────────────────────────────────────────

def test_empty_input_returns_no_chunks():
    assert chunk_markdown("") == []
    assert chunk_markdown("    \n\n   ") == []


def test_single_short_paragraph_one_chunk():
    md = "First paragraph stays whole."
    chunks = chunk_markdown(md, max_tokens=100, overlap_tokens=20)
    assert len(chunks) == 1
    assert chunks[0]["chunk_index"] == 0
    assert chunks[0]["content"] == md


def test_chunk_indices_are_zero_based_and_dense():
    """N output chunks have chunk_index 0..N-1 with no gaps."""
    md = "\n\n".join(f"para {i}" * 100 for i in range(10))
    chunks = chunk_markdown(md, max_tokens=200, overlap_tokens=20)
    assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))


# ──────────────────────────────────────────────────────────────────
# Sizing
# ──────────────────────────────────────────────────────────────────

def test_chunks_respect_max_tokens_budget():
    """No emitted chunk should be enormously larger than the budget
    unless one paragraph itself exceeded the budget."""
    # Paragraphs are each well under the budget so emitted chunks
    # should hover around it.
    para = "word " * 50  # ~250 chars per paragraph
    md = "\n\n".join([para] * 50)
    chunks = chunk_markdown(md, max_tokens=200, overlap_tokens=40)
    char_budget = 200 * 4  # 800 chars
    # Allow some slop for paragraph separators + overlap.
    for c in chunks:
        assert len(c["content"]) <= char_budget * 1.5


def test_oversized_paragraph_kept_as_single_chunk():
    """A paragraph bigger than the budget should NOT be split mid-text.
    Splitting mid-paragraph corrupts list items and code blocks."""
    huge = "x " * 5000  # ~10000 chars, way over a 200-token budget
    chunks = chunk_markdown(huge, max_tokens=200, overlap_tokens=20)
    # The whole paragraph should be one chunk because there is no
    # blank-line boundary to split on.
    assert len(chunks) == 1
    assert chunks[0]["content"] == huge.strip()


def test_overlap_carries_trailing_context_into_next_chunk():
    """The last paragraph(s) of chunk N should appear at the start of
    chunk N+1 so retrieval across boundaries works."""
    # Build paragraphs that each clearly fit, then enough of them to
    # require at least one split.
    paragraphs = [f"PARAGRAPH-{i}: " + ("body " * 30) for i in range(20)]
    md = "\n\n".join(paragraphs)
    chunks = chunk_markdown(md, max_tokens=300, overlap_tokens=80)
    assert len(chunks) >= 2

    # The last paragraph(s) of chunk 0 should appear in chunk 1.
    chunk_0_paras = chunks[0]["content"].split("\n\n")
    chunk_1_paras = chunks[1]["content"].split("\n\n")
    overlap_in_next = set(chunk_0_paras[-2:]) & set(chunk_1_paras[:3])
    assert overlap_in_next, "expected some trailing paragraphs from chunk 0 to repeat in chunk 1"


def test_zero_overlap_means_no_repeated_paragraphs():
    paragraphs = [f"P{i}: " + ("body " * 30) for i in range(10)]
    md = "\n\n".join(paragraphs)
    chunks = chunk_markdown(md, max_tokens=200, overlap_tokens=0)
    if len(chunks) >= 2:
        chunk_0_paras = set(chunks[0]["content"].split("\n\n"))
        chunk_1_paras = set(chunks[1]["content"].split("\n\n"))
        assert chunk_0_paras.isdisjoint(chunk_1_paras)


# ──────────────────────────────────────────────────────────────────
# Output shape
# ──────────────────────────────────────────────────────────────────

def test_each_chunk_has_required_fields():
    chunks = chunk_markdown("foo\n\nbar\n\nbaz", max_tokens=10, overlap_tokens=2)
    for c in chunks:
        assert set(c.keys()) >= {"chunk_index", "content", "metadata"}
        assert isinstance(c["chunk_index"], int)
        assert isinstance(c["content"], str)
        assert isinstance(c["metadata"], dict)


def test_chunks_collapse_repeated_blank_lines():
    """Repeated blank lines should not produce empty paragraphs."""
    md = "one\n\n\n\n\ntwo"
    chunks = chunk_markdown(md, max_tokens=100, overlap_tokens=0)
    assert len(chunks) == 1
    assert chunks[0]["content"] == "one\n\ntwo"
