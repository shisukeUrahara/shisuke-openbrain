"""Unit tests for worker_image.fetcher.

Layer: unit
Phase: 12.e
Run:   pytest services/workers/image/tests/unit/test_fetcher.py -v
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from worker_image.fetcher import FetchError, FetchedImage, fetch_image


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ──────────────────────────────────────────────────────────────────
# Path mode
# ──────────────────────────────────────────────────────────────────

async def test_path_mode_reads_file(tmp_path: Path):
    img = tmp_path / "snap.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\nfake")
    result = await fetch_image({"path": str(img), "caption": "test"})
    assert isinstance(result, FetchedImage)
    assert result.data == b"\x89PNG\r\n\x1a\nfake"
    assert result.mime == "image/png"
    assert result.caption == "test"


async def test_path_mode_missing(tmp_path: Path):
    with pytest.raises(FetchError, match="path not found"):
        await fetch_image({"path": str(tmp_path / "missing.jpg")})


async def test_path_mode_oversized(tmp_path: Path):
    img = tmp_path / "big.jpg"
    img.write_bytes(b"x" * 1024)
    with pytest.raises(FetchError, match="too large"):
        await fetch_image({"path": str(img)}, max_bytes=100)


async def test_path_mode_falls_back_to_jpeg_mime_when_unknown(tmp_path: Path):
    img = tmp_path / "snap.unknown_ext"
    img.write_bytes(b"data")
    result = await fetch_image({"path": str(img)}, max_bytes=10_000)
    assert result.mime == "image/jpeg"


# ──────────────────────────────────────────────────────────────────
# URL mode
# ──────────────────────────────────────────────────────────────────

async def test_url_mode_downloads_into_memory():
    body = b"\xff\xd8\xff" + b"fake jpeg" * 10

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": "image/jpeg"})

    async with _client(handler) as client:
        result = await fetch_image(
            {"url": "https://example.com/x.jpg", "caption": "wide"},
            client=client,
        )
    assert result.data == body
    assert result.mime == "image/jpeg"
    assert result.source_url == "https://example.com/x.jpg"
    assert result.caption == "wide"


async def test_url_mode_uses_response_content_type():
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"PNGDATA",
            headers={"content-type": "image/png; charset=utf-8"},
        )

    async with _client(handler) as client:
        result = await fetch_image({"url": "https://example.com/x"}, client=client)
    assert result.mime == "image/png"


async def test_url_mode_non_2xx_raises():
    async with _client(lambda req: httpx.Response(404, content=b"")) as client:
        with pytest.raises(FetchError, match="non-200"):
            await fetch_image({"url": "https://x.com/x.png"}, client=client)


async def test_url_mode_oversized_raises():
    body = b"x" * 4096

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": "image/jpeg"})

    async with _client(handler) as client:
        with pytest.raises(FetchError, match="exceeds"):
            await fetch_image(
                {"url": "https://x.com/big.jpg"},
                client=client,
                max_bytes=512,
            )


# ──────────────────────────────────────────────────────────────────
# Telegram + missing
# ──────────────────────────────────────────────────────────────────

async def test_telegram_file_id_skipped():
    with pytest.raises(FetchError, match="not yet supported"):
        await fetch_image({"file_id": "abc"})


async def test_missing_payload_raises():
    with pytest.raises(FetchError, match="missing all"):
        await fetch_image({"note": "no source"})
