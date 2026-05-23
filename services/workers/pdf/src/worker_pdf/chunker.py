"""Paragraph-based markdown chunker.

Identical contract to worker_article.chunker. Lives separately here so
the workers stay independently buildable and shippable. If we ever
refactor to a shared package these implementations must stay aligned
because the documents-module chunks they produce are interchangeable.
"""
from __future__ import annotations

from typing import Any

CHARS_PER_TOKEN = 4


def chunk_markdown(
    md: str,
    *,
    max_tokens: int = 800,
    overlap_tokens: int = 120,
) -> list[dict[str, Any]]:
    """Split `md` into chunk dicts with deterministic chunk_index."""
    if not md or not md.strip():
        return []

    paragraphs = [p for p in (block.strip() for block in md.split("\n\n")) if p]
    if not paragraphs:
        return []

    max_chars = max_tokens * CHARS_PER_TOKEN
    overlap_chars = overlap_tokens * CHARS_PER_TOKEN

    chunks: list[str] = []
    buffer: list[str] = []
    buffer_chars = 0

    for paragraph in paragraphs:
        if len(paragraph) >= max_chars:
            if buffer:
                chunks.append("\n\n".join(buffer))
                buffer, buffer_chars = [], 0
            chunks.append(paragraph)
            continue

        if buffer_chars + len(paragraph) + 2 > max_chars and buffer:
            chunks.append("\n\n".join(buffer))
            buffer, buffer_chars = _tail_overlap(buffer, overlap_chars)

        buffer.append(paragraph)
        buffer_chars += len(paragraph) + 2

    if buffer:
        chunks.append("\n\n".join(buffer))

    return [
        {"chunk_index": idx, "content": text, "metadata": {}}
        for idx, text in enumerate(chunks)
    ]


def _tail_overlap(
    paragraphs: list[str],
    overlap_chars: int,
) -> tuple[list[str], int]:
    if overlap_chars <= 0:
        return [], 0
    kept: list[str] = []
    kept_chars = 0
    for paragraph in reversed(paragraphs):
        if kept_chars + len(paragraph) > overlap_chars and kept:
            break
        kept.insert(0, paragraph)
        kept_chars += len(paragraph) + 2
    return kept, kept_chars
