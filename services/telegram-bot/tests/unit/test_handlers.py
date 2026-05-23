"""Unit tests for brain_bot.handlers — pure dispatch logic.

The dispatch function is the single decision point: every incoming
message turns into an Action here. Cover the full classification
table so a change to the routing rules announces itself in this
suite.

Layer: unit
Phase: 11
Run:   pytest services/telegram-bot/tests/unit/test_handlers.py -v
"""
from __future__ import annotations

import pytest

from brain_bot.handlers import (
    Action,
    ActionKind,
    NormalizedMessage,
    dispatch,
    extract_urls,
)


OWNER = 12345
STRANGER = 99999


def _msg(**kwargs) -> NormalizedMessage:
    defaults = {"user_id": OWNER, "message_id": 1}
    defaults.update(kwargs)
    return NormalizedMessage(**defaults)


# ──────────────────────────────────────────────────────────────────
# Owner check
# ──────────────────────────────────────────────────────────────────

def test_non_owner_text_is_ignored():
    """A stranger sending text never produces a side effect."""
    action = dispatch(_msg(user_id=STRANGER, text="hi"), owner_id=OWNER)
    assert action.kind == ActionKind.IGNORE
    assert action.reply is None


def test_non_owner_voice_is_ignored():
    action = dispatch(
        _msg(user_id=STRANGER, voice_file_id="v1", voice_duration_s=5),
        owner_id=OWNER,
    )
    assert action.kind == ActionKind.IGNORE


def test_non_owner_photo_is_ignored():
    action = dispatch(_msg(user_id=STRANGER, photo_file_id="p1"), owner_id=OWNER)
    assert action.kind == ActionKind.IGNORE


def test_non_owner_document_is_ignored():
    action = dispatch(
        _msg(
            user_id=STRANGER,
            document_file_id="d1",
            document_mime_type="application/pdf",
        ),
        owner_id=OWNER,
    )
    assert action.kind == ActionKind.IGNORE


# ──────────────────────────────────────────────────────────────────
# Text path
# ──────────────────────────────────────────────────────────────────

def test_owner_plain_text_captures():
    action = dispatch(_msg(text="quick thought"), owner_id=OWNER)
    assert action.kind == ActionKind.CAPTURE_TEXT
    assert action.payload["content"] == "quick thought"
    assert action.payload["metadata"]["source"] == "telegram"
    assert action.payload["metadata"]["source_ref"] == "tg://msg/1"
    assert action.reply == "✅ saved"


def test_owner_text_with_one_url_enqueues_article():
    action = dispatch(
        _msg(text="check this https://example.com/post"),
        owner_id=OWNER,
    )
    assert action.kind == ActionKind.ENQUEUE
    batch = action.payload["batch"]
    assert len(batch) == 1
    item = batch[0]
    assert item["queue"] == "ingest:article"
    assert item["job"]["url"] == "https://example.com/post"
    assert item["job"]["note"].startswith("check this")
    assert action.reply == "🔗 queued 1 url(s)"


def test_owner_youtube_url_enqueues_youtube():
    action = dispatch(
        _msg(text="https://youtu.be/abc123"),
        owner_id=OWNER,
    )
    item = action.payload["batch"][0]
    assert item["queue"] == "ingest:youtube"


def test_owner_youtube_full_url_enqueues_youtube():
    action = dispatch(
        _msg(text="https://www.youtube.com/watch?v=xyz"),
        owner_id=OWNER,
    )
    item = action.payload["batch"][0]
    assert item["queue"] == "ingest:youtube"


def test_owner_multiple_urls_enqueue_multiple_jobs():
    action = dispatch(
        _msg(text="https://example.com/a and https://example.com/b"),
        owner_id=OWNER,
    )
    queues = [item["queue"] for item in action.payload["batch"]]
    assert queues == ["ingest:article", "ingest:article"]
    assert action.reply == "🔗 queued 2 url(s)"


def test_duplicate_urls_collapse():
    action = dispatch(
        _msg(text="https://example.com/x https://example.com/x"),
        owner_id=OWNER,
    )
    assert len(action.payload["batch"]) == 1


def test_trailing_punctuation_stripped_from_urls():
    action = dispatch(
        _msg(text="thoughts on https://example.com/post."),
        owner_id=OWNER,
    )
    assert action.payload["batch"][0]["job"]["url"] == "https://example.com/post"


# ──────────────────────────────────────────────────────────────────
# Voice
# ──────────────────────────────────────────────────────────────────

def test_owner_voice_enqueues_voice_job():
    action = dispatch(
        _msg(voice_file_id="voice123", voice_duration_s=42),
        owner_id=OWNER,
    )
    assert action.kind == ActionKind.ENQUEUE
    assert action.payload["queue"] == "ingest:voice"
    assert action.payload["job"]["file_id"] == "voice123"
    assert action.payload["job"]["duration_s"] == 42
    assert action.reply == "🎙️ transcribing"


# ──────────────────────────────────────────────────────────────────
# Photo
# ──────────────────────────────────────────────────────────────────

def test_owner_photo_enqueues_image_job():
    action = dispatch(
        _msg(photo_file_id="photo456", photo_caption="receipt"),
        owner_id=OWNER,
    )
    assert action.kind == ActionKind.ENQUEUE
    assert action.payload["queue"] == "ingest:image"
    assert action.payload["job"]["file_id"] == "photo456"
    assert action.payload["job"]["caption"] == "receipt"
    assert action.reply == "🖼️ analyzing image"


# ──────────────────────────────────────────────────────────────────
# Document
# ──────────────────────────────────────────────────────────────────

def test_owner_pdf_by_mime_enqueues_pdf_job():
    action = dispatch(
        _msg(
            document_file_id="doc789",
            document_file_name="report.pdf",
            document_mime_type="application/pdf",
        ),
        owner_id=OWNER,
    )
    assert action.kind == ActionKind.ENQUEUE
    assert action.payload["queue"] == "ingest:pdf"
    assert action.payload["job"]["file_name"] == "report.pdf"
    assert action.reply == "📄 pdf queued"


def test_owner_pdf_by_extension_enqueues_pdf_job():
    """Some Telegram clients ship application/octet-stream for .pdf —
    fall back to filename extension."""
    action = dispatch(
        _msg(
            document_file_id="doc789",
            document_file_name="report.pdf",
            document_mime_type="application/octet-stream",
        ),
        owner_id=OWNER,
    )
    assert action.kind == ActionKind.ENQUEUE
    assert action.payload["queue"] == "ingest:pdf"


def test_owner_non_pdf_document_replies_politely():
    action = dispatch(
        _msg(
            document_file_id="doc789",
            document_file_name="image.png",
            document_mime_type="image/png",
        ),
        owner_id=OWNER,
    )
    assert action.kind == ActionKind.REPLY
    assert "PDF" in (action.reply or "")


# ──────────────────────────────────────────────────────────────────
# Empty / unsupported
# ──────────────────────────────────────────────────────────────────

def test_owner_empty_message_is_ignored():
    action = dispatch(_msg(), owner_id=OWNER)
    assert action.kind == ActionKind.IGNORE


# ──────────────────────────────────────────────────────────────────
# extract_urls helper
# ──────────────────────────────────────────────────────────────────

def test_extract_urls_finds_one():
    assert extract_urls("see https://x.com") == ["https://x.com"]


def test_extract_urls_preserves_order_and_dedupes():
    result = extract_urls("https://a.com https://b.com https://a.com")
    assert result == ["https://a.com", "https://b.com"]


def test_extract_urls_ignores_plain_words():
    assert extract_urls("no link here") == []


def test_extract_urls_handles_https_and_http():
    result = extract_urls("http://a.com https://b.com")
    assert result == ["http://a.com", "https://b.com"]
