"""Pure dispatch logic for incoming Telegram messages.

This module contains zero I/O. It takes a normalized message dict,
returns a typed Action describing what the server layer should do
next. The split keeps unit tests trivial: feed in dict fixtures,
assert on the returned Action.

Why this matters: aiogram's Message object is awkward to mock and
its API drifts between minor versions. Normalize once at the edge,
work with our own immutable shape everywhere else.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ──────────────────────────────────────────────────────────────────
# Normalized input
# ──────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class NormalizedMessage:
    """Subset of an aiogram Message that handlers actually need.

    Created from an aiogram Message in server.py via to_normalized().
    Plain dict-like so tests do not import aiogram at all.
    """
    user_id: int
    message_id: int
    text: str | None = None
    voice_file_id: str | None = None
    voice_duration_s: int | None = None
    photo_file_id: str | None = None
    photo_caption: str | None = None
    document_file_id: str | None = None
    document_file_name: str | None = None
    document_mime_type: str | None = None


# ──────────────────────────────────────────────────────────────────
# Actions the server layer can be told to perform
# ──────────────────────────────────────────────────────────────────

class ActionKind(str, Enum):
    IGNORE = "ignore"                  # silently drop (non-owner, unsupported)
    REPLY  = "reply"                   # send a plain reply (e.g. "only owner")
    CAPTURE_TEXT = "capture_text"      # call mcp capture
    ENQUEUE = "enqueue"                # lpush onto a redis list


_YOUTUBE_HOSTS = ("youtu.be", "youtube.com", "m.youtube.com")
_URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)


@dataclass(frozen=True)
class Action:
    kind: ActionKind
    # Payload shape depends on kind. Documented per-kind below.
    payload: dict[str, Any] = field(default_factory=dict)
    # Optional user-facing reply, sent alongside the action.
    reply: str | None = None


# ──────────────────────────────────────────────────────────────────
# Public entry point
# ──────────────────────────────────────────────────────────────────

def dispatch(msg: NormalizedMessage, *, owner_id: int) -> Action:
    """Decide what the server should do with this message.

    Drops any non-owner message silently. Owner messages route to:
      - text without URLs → CAPTURE_TEXT
      - text with URLs    → ENQUEUE one job per URL (article / youtube)
      - voice             → ENQUEUE on ingest:voice
      - photo             → ENQUEUE on ingest:image
      - document (pdf)    → ENQUEUE on ingest:pdf
      - any other         → IGNORE with a polite reply
    """
    if msg.user_id != owner_id:
        return Action(kind=ActionKind.IGNORE)

    if msg.voice_file_id:
        return Action(
            kind=ActionKind.ENQUEUE,
            payload={
                "queue": "ingest:voice",
                "job": {
                    "file_id": msg.voice_file_id,
                    "duration_s": msg.voice_duration_s,
                    "message_id": msg.message_id,
                },
            },
            reply="🎙️ transcribing",
        )

    if msg.photo_file_id:
        return Action(
            kind=ActionKind.ENQUEUE,
            payload={
                "queue": "ingest:image",
                "job": {
                    "file_id": msg.photo_file_id,
                    "caption": msg.photo_caption,
                    "message_id": msg.message_id,
                },
            },
            reply="🖼️ analyzing image",
        )

    if msg.document_file_id:
        if _is_pdf(msg.document_mime_type, msg.document_file_name):
            return Action(
                kind=ActionKind.ENQUEUE,
                payload={
                    "queue": "ingest:pdf",
                    "job": {
                        "file_id": msg.document_file_id,
                        "file_name": msg.document_file_name,
                        "mime_type": msg.document_mime_type,
                        "message_id": msg.message_id,
                    },
                },
                reply="📄 pdf queued",
            )
        # Some other document kind we do not handle yet.
        return Action(
            kind=ActionKind.REPLY,
            reply=(
                "only PDFs are supported in the document handler right now"
            ),
        )

    if msg.text:
        urls = extract_urls(msg.text)
        if urls:
            jobs = [
                {
                    "queue": _queue_for_url(url),
                    "job": {
                        "url": url,
                        "note": msg.text,
                        "message_id": msg.message_id,
                    },
                }
                for url in urls
            ]
            return Action(
                kind=ActionKind.ENQUEUE,
                payload={"batch": jobs},
                reply=f"🔗 queued {len(jobs)} url(s)",
            )
        return Action(
            kind=ActionKind.CAPTURE_TEXT,
            payload={
                "content": msg.text,
                "metadata": {
                    "source": "telegram",
                    "source_ref": f"tg://msg/{msg.message_id}",
                },
            },
            reply="✅ saved",
        )

    # Unknown / empty payload.
    return Action(kind=ActionKind.IGNORE)


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────

def extract_urls(text: str) -> list[str]:
    """Return every http(s) URL embedded in `text`, preserving order
    and dropping duplicates."""
    seen: set[str] = set()
    out: list[str] = []
    for hit in _URL_RE.findall(text):
        # Strip common trailing punctuation that the regex grabs.
        cleaned = hit.rstrip(".,;:)!?]>'\"")
        if cleaned not in seen:
            seen.add(cleaned)
            out.append(cleaned)
    return out


def _queue_for_url(url: str) -> str:
    lower = url.lower()
    if any(host in lower for host in _YOUTUBE_HOSTS):
        return "ingest:youtube"
    return "ingest:article"


def _is_pdf(mime: str | None, filename: str | None) -> bool:
    if mime and "pdf" in mime.lower():
        return True
    if filename and filename.lower().endswith(".pdf"):
        return True
    return False
