"""Unit tests for worker_audio.fetcher.

Layer: unit
Phase: 12.d
Run:   pytest services/workers/audio/tests/unit/test_fetcher.py -v
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from worker_audio.fetcher import FetchError, FetchedAudio, fetch_audio


def _client_with_handler(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ──────────────────────────────────────────────────────────────────
# Path mode
# ──────────────────────────────────────────────────────────────────

async def test_path_mode_returns_local_file(tmp_path: Path):
    clip = tmp_path / "voice.ogg"
    clip.write_bytes(b"OGGfake")
    result = await fetch_audio({"path": str(clip), "title": "memo"})
    assert isinstance(result, FetchedAudio)
    assert result.path == clip
    assert result.owned is False
    assert result.title == "memo"


async def test_path_mode_missing_file_raises(tmp_path: Path):
    with pytest.raises(FetchError, match="path not found"):
        await fetch_audio({"path": str(tmp_path / "missing.ogg")})


async def test_path_mode_oversized_raises(tmp_path: Path):
    clip = tmp_path / "huge.mp3"
    clip.write_bytes(b"x" * 1024)
    with pytest.raises(FetchError, match="too large"):
        await fetch_audio({"path": str(clip)}, max_bytes=10)


# ──────────────────────────────────────────────────────────────────
# Plain HTTP URL mode
# ──────────────────────────────────────────────────────────────────

async def test_http_url_downloads_to_owned_temp():
    body = b"FAKEMP3" * 32

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    async with _client_with_handler(handler) as client:
        result = await fetch_audio(
            {"url": "https://example.com/clip.mp3"}, client=client
        )
    assert result.owned is True
    assert result.path.exists()
    assert result.path.read_bytes() == body
    result.path.unlink()


async def test_http_url_non_200_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, content=b"")

    async with _client_with_handler(handler) as client:
        with pytest.raises(FetchError, match="non-200"):
            await fetch_audio({"url": "https://x.com/c.mp3"}, client=client)


async def test_http_url_oversized_raises():
    body = b"x" * 4096

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body)

    async with _client_with_handler(handler) as client:
        with pytest.raises(FetchError, match="exceeds"):
            await fetch_audio(
                {"url": "https://x.com/big.mp3"},
                client=client,
                max_bytes=512,
            )


# ──────────────────────────────────────────────────────────────────
# Telegram file_id mode
# ──────────────────────────────────────────────────────────────────

async def test_telegram_file_id_not_yet_supported():
    """Documented gap — until we wire TELEGRAM_BOT_TOKEN into the
    worker, file_id payloads are rejected with a clear error."""
    with pytest.raises(FetchError, match="not yet supported"):
        await fetch_audio({"file_id": "abc", "duration_s": 5})


# ──────────────────────────────────────────────────────────────────
# Missing payload
# ──────────────────────────────────────────────────────────────────

async def test_missing_all_inputs_raises():
    with pytest.raises(FetchError, match="missing all"):
        await fetch_audio({"note": "nothing to fetch"})
