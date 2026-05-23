"""Unit tests for worker_pdf.chunker.

Mirrors the worker_article chunker contract. The two implementations
must stay aligned because chunks they produce are interchangeable
when stored under the documents module.

Layer: unit
Phase: 12.c
Run:   pytest services/workers/pdf/tests/unit/test_chunker.py -v
"""
from __future__ import annotations

import pytest

from worker_pdf.chunker import chunk_markdown


def test_empty_input_returns_no_chunks():
    assert chunk_markdown("") == []


def test_single_short_paragraph_one_chunk():
    chunks = chunk_markdown("Just a brief note.", max_tokens=100, overlap_tokens=20)
    assert len(chunks) == 1
    assert chunks[0]["chunk_index"] == 0


def test_dense_chunk_indices():
    md = "\n\n".join(f"para {i}" * 100 for i in range(8))
    chunks = chunk_markdown(md, max_tokens=200, overlap_tokens=20)
    assert [c["chunk_index"] for c in chunks] == list(range(len(chunks)))


def test_oversized_paragraph_kept_whole():
    huge = "x " * 5000
    chunks = chunk_markdown(huge, max_tokens=200, overlap_tokens=20)
    assert len(chunks) == 1
    assert chunks[0]["content"] == huge.strip()


def test_overlap_carries_context_across_chunks():
    paragraphs = [f"PARA-{i}: " + ("body " * 30) for i in range(20)]
    md = "\n\n".join(paragraphs)
    chunks = chunk_markdown(md, max_tokens=300, overlap_tokens=80)
    assert len(chunks) >= 2

    chunk_0 = set(chunks[0]["content"].split("\n\n"))
    chunk_1 = set(chunks[1]["content"].split("\n\n"))
    assert chunk_0 & chunk_1, "expected at least one overlapping paragraph"


def test_zero_overlap_means_disjoint_chunks():
    paragraphs = [f"P{i}: " + ("body " * 30) for i in range(10)]
    md = "\n\n".join(paragraphs)
    chunks = chunk_markdown(md, max_tokens=200, overlap_tokens=0)
    if len(chunks) >= 2:
        assert set(chunks[0]["content"].split("\n\n")).isdisjoint(
            set(chunks[1]["content"].split("\n\n"))
        )


def test_required_chunk_fields():
    chunks = chunk_markdown("a\n\nb\n\nc", max_tokens=10, overlap_tokens=2)
    for c in chunks:
        assert {"chunk_index", "content", "metadata"} <= set(c.keys())
