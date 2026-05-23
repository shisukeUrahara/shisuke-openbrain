"""Unit tests for worker_pdf.fetcher.

Layer: unit
Phase: 12.c
Run:   pytest services/workers/pdf/tests/unit/test_fetcher.py -v
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from worker_pdf.fetcher import FetchError, fetch_pdf


def _client_with_handler(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ──────────────────────────────────────────────────────────────────
# Path mode (no network)
# ──────────────────────────────────────────────────────────────────

async def test_path_mode_returns_path_unchanged(tmp_path: Path):
    pdf = tmp_path / "small.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")
    path, owned = await fetch_pdf({"path": str(pdf)})
    assert path == pdf
    assert owned is False


async def test_path_mode_missing_file_raises(tmp_path: Path):
    with pytest.raises(FetchError, match="path not found"):
        await fetch_pdf({"path": str(tmp_path / "does-not-exist.pdf")})


async def test_path_mode_oversized_raises(tmp_path: Path):
    pdf = tmp_path / "big.pdf"
    pdf.write_bytes(b"x" * 1024)
    with pytest.raises(FetchError, match="too large"):
        await fetch_pdf({"path": str(pdf)}, max_bytes=10)


# ──────────────────────────────────────────────────────────────────
# URL mode
# ──────────────────────────────────────────────────────────────────

async def test_url_mode_downloads_and_returns_owned_temp(tmp_path):
    body = b"%PDF-1.4 here is a fake pdf body"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    async with _client_with_handler(handler) as client:
        path, owned = await fetch_pdf(
            {"url": "https://example.com/report.pdf"}, client=client
        )
    assert owned is True
    assert path.exists()
    assert path.read_bytes() == body
    # Cleanup so we don't leak temp files in repeated runs.
    path.unlink()


async def test_url_mode_non_200_raises(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"busy")

    async with _client_with_handler(handler) as client:
        with pytest.raises(FetchError, match="non-200"):
            await fetch_pdf(
                {"url": "https://x.com/p.pdf"}, client=client
            )


async def test_url_mode_oversized_raises(tmp_path):
    """If the streamed body exceeds max_bytes the fetcher must abort
    before filling the disk."""
    body = b"x" * 2048

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    async with _client_with_handler(handler) as client:
        with pytest.raises(FetchError, match="exceeds"):
            await fetch_pdf(
                {"url": "https://x.com/big.pdf"},
                client=client,
                max_bytes=1024,
            )


# ──────────────────────────────────────────────────────────────────
# Missing payload
# ──────────────────────────────────────────────────────────────────

async def test_neither_path_nor_url_raises():
    with pytest.raises(FetchError, match="missing both"):
        await fetch_pdf({"note": "no idea what to download"})
