"""PDF -> markdown extractor.

We hide the underlying parser behind a small Protocol so tests inject
a trivial fake without touching the heavy dep.

Default implementation: pymupdf (~5MB, no PyTorch). Suitable for any
PDF with a text layer (articles, reports, papers, ebooks). Scanned
PDFs without a text layer fall through to "extract too short" and
the worker logs + skips. For OCR coverage swap in a Docling-backed
extractor later — the Protocol is the seam.
"""
from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


logger = logging.getLogger("worker_pdf.extractor")


@dataclass(frozen=True)
class ExtractedDocument:
    title: str
    markdown: str
    sha256: str
    page_count: int | None = None


class PdfExtractor(Protocol):
    """Protocol every extractor must satisfy. Lets tests pass a
    trivial fake without importing pymupdf or Docling."""

    def extract(self, path: Path) -> ExtractedDocument: ...


class PymupdfExtractor:
    """Default extractor backed by pymupdf.

    pymupdf's `page.get_text("markdown")` mode emits headers, lists,
    bold, italic, and basic table structure as proper markdown,
    matching what the chunker expects. We concat pages with blank-line
    separators so the chunker can use them as natural split points.
    """

    def extract(self, path: Path) -> ExtractedDocument:
        # Local import: keeps test collection cheap and idle-mode
        # imports light. pymupdf imports a C extension that does some
        # one-time setup.
        import fitz  # provided by the pymupdf package

        doc = fitz.open(str(path))
        try:
            pages_text: list[str] = []
            for page in doc:
                # Plain text mode preserves paragraph boundaries via
                # blank lines, which is what our chunker needs. The
                # "markdown" format option is unstable across pymupdf
                # versions (1.24 raises AssertionError on it) so we
                # stick with the universally supported text mode.
                text = page.get_text("text")
                cleaned = _normalize_page_text(text)
                if cleaned:
                    pages_text.append(cleaned)

            markdown = "\n\n".join(pages_text).strip()
            page_count = doc.page_count
            title = _title_from_metadata(doc) or path.stem
        finally:
            doc.close()

        sha = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        return ExtractedDocument(
            title=title,
            markdown=markdown,
            sha256=sha,
            page_count=page_count,
        )


# Backwards compatibility for any caller still importing the old
# class name. New code should prefer PymupdfExtractor.
DoclingExtractor = PymupdfExtractor


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

def _title_from_metadata(doc) -> str | None:  # type: ignore[no-untyped-def]
    """Try the PDF metadata first; fall back to None so the caller
    can derive a title from the filename."""
    meta = getattr(doc, "metadata", None) or {}
    title = (meta.get("title") or meta.get("Title") or "").strip()
    if title:
        return title
    return None


_MULTI_BLANK_LINE = re.compile(r"\n{3,}")


def _normalize_page_text(text: str) -> str:
    """Collapse runs of blank lines and strip trailing whitespace per
    line. pymupdf's markdown mode occasionally emits 4-5 blank lines
    in a row when crossing column boundaries; the chunker would treat
    each as its own paragraph break, which hurts overlap heuristics."""
    if not text:
        return ""
    lines = [line.rstrip() for line in text.splitlines()]
    collapsed = "\n".join(lines)
    return _MULTI_BLANK_LINE.sub("\n\n", collapsed).strip()
