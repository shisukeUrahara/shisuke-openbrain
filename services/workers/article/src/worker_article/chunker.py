"""Paragraph-based markdown chunker.

Pure: takes a markdown string + size knobs, returns a list of chunk
dicts ready for MCP add_chunks. Token counts are approximated by
characters (4 chars ≈ 1 token); good enough for splitting heuristics
and avoids a tiktoken dependency.

Design choices:
- Split on blank-line boundaries (paragraphs / lists / fenced code
  blocks) rather than mid-paragraph so chunk boundaries land on
  meaningful semantic breaks.
- Carry `overlap_tokens` worth of trailing context into the next
  chunk so a question whose answer straddles a boundary still
  retrieves both sides.
- Never split a single paragraph that is longer than the chunk
  budget — return it as its own oversized chunk and let the embed
  provider deal with it. Splitting mid-paragraph mangles list items
  and code blocks; the cost of one oversized chunk is small.
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
        # Paragraph alone is bigger than the budget -- flush whatever
        # we have, then emit the oversized paragraph as its own chunk.
        if len(paragraph) >= max_chars:
            if buffer:
                chunks.append("\n\n".join(buffer))
                buffer, buffer_chars = [], 0
            chunks.append(paragraph)
            continue

        # Adding this paragraph would overflow -- flush, then start a
        # new buffer that begins with the overlap tail.
        if buffer_chars + len(paragraph) + 2 > max_chars and buffer:
            chunks.append("\n\n".join(buffer))
            buffer, buffer_chars = _tail_overlap(buffer, overlap_chars)

        buffer.append(paragraph)
        buffer_chars += len(paragraph) + 2  # +2 for the separator

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
    """Return the last paragraphs whose combined size is just under
    `overlap_chars`. Used to seed the next chunk with shared
    context."""
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
