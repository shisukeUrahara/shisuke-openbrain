"""Vision-language analyzer that produces OCR + description.

Hidden behind the VisionAnalyzer Protocol so a future swap to a
local VLM (e.g. Ollama Qwen-VL) only touches one class.

The default OpenRouterVisionAnalyzer sends a single chat-completion
call with the image base64-embedded in the content. Output is
markdown with two sections so the chunker can split sensibly:

    ## Extracted Text
    <OCR>

    ## Description
    <description>

Prompt design choices:
- The system message says "the user saved this to their second
  brain" so the model produces output useful for future retrieval,
  not generic captions.
- We ask for exact OCR first (a deterministic span) then the
  description, so the model commits to the visible text before
  inventing context.
"""
from __future__ import annotations

import base64
import hashlib
import logging
from dataclasses import dataclass
from typing import Protocol

import httpx


logger = logging.getLogger("worker_image.analyzer")


_OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
_DEFAULT_MODEL = "qwen/qwen-2.5-vl-7b-instruct"

_SYSTEM_PROMPT = (
    "You are analyzing an image the user just saved to their second "
    "brain. Two tasks: (1) extract every visible text verbatim (OCR); "
    "(2) describe what the image shows in 2-4 sentences, written for "
    "future retrieval — be specific about subjects, setting, time of "
    "day, mood, and any handwritten or printed text. Output markdown "
    "with two sections exactly: ## Extracted Text and ## Description. "
    "If there is no visible text, write 'None' under Extracted Text."
)


class AnalysisError(RuntimeError):
    """Raised when the VLM call fails or its response cannot be parsed."""


@dataclass(frozen=True)
class AnalyzedImage:
    title: str
    markdown: str
    sha256: str


class VisionAnalyzer(Protocol):
    async def analyze(
        self, *, image_bytes: bytes, mime: str, caption: str | None
    ) -> AnalyzedImage: ...


class OpenRouterVisionAnalyzer:
    def __init__(
        self,
        *,
        api_key: str,
        model: str = _DEFAULT_MODEL,
        timeout: float = 60.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is required")
        self._api_key = api_key
        self._model = model
        self._timeout = timeout
        self._client = client

    async def analyze(
        self,
        *,
        image_bytes: bytes,
        mime: str,
        caption: str | None,
    ) -> AnalyzedImage:
        b64 = base64.b64encode(image_bytes).decode()
        data_url = f"data:{mime};base64,{b64}"

        user_parts: list[dict] = [
            {"type": "text", "text": _build_user_prompt(caption)},
            {"type": "image_url", "image_url": {"url": data_url}},
        ]
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_parts},
            ],
        }

        if self._client is not None:
            response = await self._client.post(
                _OPENROUTER_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        else:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    _OPENROUTER_URL,
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=payload,
                )

        if response.status_code != 200:
            raise AnalysisError(
                f"openrouter VLM failed: status={response.status_code} body={response.text[:500]}"
            )

        body = response.json()
        try:
            content = body["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise AnalysisError(f"unexpected response shape: {body!r}") from exc

        if isinstance(content, list):
            # Some providers wrap text in a content array.
            content = "\n".join(
                part.get("text", "") for part in content if isinstance(part, dict)
            )

        if not isinstance(content, str) or not content.strip():
            raise AnalysisError(f"empty VLM response: {body!r}")

        markdown = _wrap_with_caption(content.strip(), caption)
        title = _title_from_caption_or_content(caption, content)
        sha = hashlib.sha256(markdown.encode("utf-8")).hexdigest()
        return AnalyzedImage(title=title, markdown=markdown, sha256=sha)


def _build_user_prompt(caption: str | None) -> str:
    if caption and caption.strip():
        return (
            f"User caption (their context for saving this): {caption.strip()}\n\n"
            f"Now perform the OCR + description per the system instructions."
        )
    return "Perform the OCR + description per the system instructions."


def _wrap_with_caption(model_output: str, caption: str | None) -> str:
    if caption and caption.strip():
        return f"> User caption: {caption.strip()}\n\n{model_output}"
    return model_output


def _title_from_caption_or_content(caption: str | None, content: str) -> str:
    if caption and caption.strip():
        return caption.strip()[:120]
    # Take the first descriptive line under '## Description' if we can.
    in_desc = False
    for line in content.splitlines():
        if line.strip().startswith("## Description"):
            in_desc = True
            continue
        if in_desc and line.strip():
            return line.strip()[:120]
    # Otherwise the first non-empty line of output.
    for line in content.splitlines():
        if line.strip() and not line.strip().startswith("#"):
            return line.strip()[:120]
    return "image"
