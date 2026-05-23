"""Unit tests for worker_image.analyzer.OpenRouterVisionAnalyzer.

Mocks the OpenRouter chat-completions endpoint at the httpx wire
level. Confirms request shape (image base64-encoded in a data URL,
system prompt sent, vision model name), happy-path response
parsing, caption wrapping, and every failure surface.

Layer: unit
Phase: 12.e
Run:   pytest services/workers/image/tests/unit/test_analyzer.py -v
"""
from __future__ import annotations

import base64
import json

import httpx
import pytest

from worker_image.analyzer import (
    AnalysisError,
    AnalyzedImage,
    OpenRouterVisionAnalyzer,
)


_IMAGE_BYTES = b"\xff\xd8\xff" + b"fake jpeg body"


def _success(content_text: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "id": "x",
            "choices": [
                {"message": {"role": "assistant", "content": content_text}}
            ],
        },
    )


async def test_request_shape(monkeypatch):
    captured: dict = {}

    def handler(req: httpx.Request) -> httpx.Response:
        captured["url"] = str(req.url)
        captured["auth"] = req.headers.get("authorization")
        captured["body"] = json.loads(req.read())
        return _success(
            "## Extracted Text\nHELLO\n\n## Description\nA sign that reads HELLO."
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        analyzer = OpenRouterVisionAnalyzer(api_key="sk-test", client=client)
        result = await analyzer.analyze(
            image_bytes=_IMAGE_BYTES, mime="image/jpeg", caption=None
        )

    assert isinstance(result, AnalyzedImage)
    assert "HELLO" in result.markdown
    assert "## Description" in result.markdown
    assert len(result.sha256) == 64

    body = captured["body"]
    assert body["model"] == "qwen/qwen-2.5-vl-7b-instruct"
    assert "second brain" in body["messages"][0]["content"]
    parts = body["messages"][1]["content"]
    assert any(p.get("type") == "text" for p in parts)
    image_part = next(p for p in parts if p.get("type") == "image_url")
    expected_b64 = base64.b64encode(_IMAGE_BYTES).decode()
    assert image_part["image_url"]["url"] == f"data:image/jpeg;base64,{expected_b64}"
    assert captured["auth"] == "Bearer sk-test"
    assert "openrouter.ai/api/v1/chat/completions" in captured["url"]


async def test_caption_wraps_into_markdown():
    def handler(req: httpx.Request) -> httpx.Response:
        return _success(
            "## Extracted Text\nNone\n\n## Description\nA receipt for a book purchase."
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        analyzer = OpenRouterVisionAnalyzer(api_key="sk-test", client=client)
        result = await analyzer.analyze(
            image_bytes=_IMAGE_BYTES,
            mime="image/png",
            caption="book receipt",
        )
    # The caption gets prepended as a blockquote so the chunker keeps
    # it grouped with the description.
    assert result.markdown.startswith("> User caption: book receipt")
    # And the title is derived from the caption.
    assert result.title == "book receipt"


async def test_title_falls_back_to_description_when_no_caption():
    def handler(req: httpx.Request) -> httpx.Response:
        return _success(
            "## Extracted Text\nMARKET\n\n## Description\nA bustling outdoor farmers market at dawn."
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        analyzer = OpenRouterVisionAnalyzer(api_key="sk-test", client=client)
        result = await analyzer.analyze(
            image_bytes=_IMAGE_BYTES, mime="image/jpeg", caption=None
        )
    assert "farmers market" in result.title.lower()


async def test_non_200_raises():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: httpx.Response(500, text="oops"))
    ) as client:
        analyzer = OpenRouterVisionAnalyzer(api_key="sk-test", client=client)
        with pytest.raises(AnalysisError, match="500"):
            await analyzer.analyze(
                image_bytes=_IMAGE_BYTES, mime="image/jpeg", caption=None
            )


async def test_unexpected_response_shape_raises():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(200, json={"unexpected": "shape"})
        )
    ) as client:
        analyzer = OpenRouterVisionAnalyzer(api_key="sk-test", client=client)
        with pytest.raises(AnalysisError, match="unexpected"):
            await analyzer.analyze(
                image_bytes=_IMAGE_BYTES, mime="image/jpeg", caption=None
            )


async def test_empty_content_raises():
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda req: _success(""))
    ) as client:
        analyzer = OpenRouterVisionAnalyzer(api_key="sk-test", client=client)
        with pytest.raises(AnalysisError, match="empty"):
            await analyzer.analyze(
                image_bytes=_IMAGE_BYTES, mime="image/jpeg", caption=None
            )


async def test_content_array_format_is_concatenated():
    """Some providers wrap text in a content array of dicts."""
    array_content = [
        {"type": "text", "text": "## Extracted Text\nALPHA\n\n"},
        {"type": "text", "text": "## Description\nbeta line."},
    ]

    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"role": "assistant", "content": array_content}}
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        analyzer = OpenRouterVisionAnalyzer(api_key="sk-test", client=client)
        result = await analyzer.analyze(
            image_bytes=_IMAGE_BYTES, mime="image/jpeg", caption=None
        )
    assert "ALPHA" in result.markdown
    assert "beta line" in result.markdown


def test_empty_api_key_raises_at_construction():
    with pytest.raises(ValueError, match="OPENROUTER_API_KEY"):
        OpenRouterVisionAnalyzer(api_key="")
