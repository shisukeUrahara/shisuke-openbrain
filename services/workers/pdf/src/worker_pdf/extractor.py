"""PDF -> markdown extractor via Docling.

We hide Docling behind a small interface so unit tests can swap in a
trivial fake extractor without installing the (large) Docling
dependency tree.

The default extractor is lazily constructed because Docling pulls in
heavy imports — we do not want test collection or `python -m
worker_pdf` (idle mode) to pay that cost.
"""
from __future__ import annotations

import hashlib
import logging
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
    """Abstract extractor protocol. process_one accepts any object
    that satisfies this so tests can inject a fake."""

    def extract(self, path: Path) -> ExtractedDocument: ...


class DoclingExtractor:
    """Default extractor. The DocumentConverter is constructed lazily
    on first .extract() call so cold start cost does not appear in
    unit tests or in idle mode."""

    def __init__(self) -> None:
        self._converter = None

    def extract(self, path: Path) -> ExtractedDocument:
        from docling.document_converter import DocumentConverter  # local import

        if self._converter is None:
            logger.info("initialising docling DocumentConverter (cold start)")
            self._converter = DocumentConverter()

        result = self._converter.convert(str(path))
        document = result.document
        markdown = document.export_to_markdown()
        title = _title_from_docling(document) or path.stem
        page_count = _page_count(document)
        sha = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        return ExtractedDocument(
            title=title,
            markdown=markdown,
            sha256=sha,
            page_count=page_count,
        )


def _title_from_docling(document) -> str | None:  # type: ignore[no-untyped-def]
    """Best-effort title extraction across docling versions."""
    for attr in ("title", "name"):
        value = getattr(document, attr, None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _page_count(document) -> int | None:  # type: ignore[no-untyped-def]
    for attr in ("num_pages", "page_count"):
        value = getattr(document, attr, None)
        if isinstance(value, int) and value > 0:
            return value
    pages = getattr(document, "pages", None)
    if hasattr(pages, "__len__"):
        try:
            return len(pages)
        except TypeError:
            return None
    return None
