"""Unit tests for brain_bot.server.execute — Action runner.

Verifies that each Action kind triggers the expected side effects.
McpClient and QueueClient are replaced with tiny stub objects that
record calls rather than reach the network.

Layer: unit
Phase: 11
Run:   pytest services/telegram-bot/tests/unit/test_execute.py -v
"""
from __future__ import annotations

from typing import Any

import pytest

from brain_bot.handlers import Action, ActionKind
from brain_bot.mcp_client import McpError
from brain_bot.server import execute


class _StubMcp:
    def __init__(self, *, fail: bool = False) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self._fail = fail

    async def capture(self, content: str, *, metadata=None) -> dict[str, Any]:
        self.calls.append((content, metadata))
        if self._fail:
            raise McpError("forced failure")
        return {"id": "x", "fingerprint": "f", "embedded": True}


class _StubQueue:
    def __init__(self) -> None:
        self.pushes: list[tuple[str, dict[str, Any]]] = []

    async def enqueue(self, queue: str, job: dict[str, Any]) -> int:
        self.pushes.append((queue, job))
        return len(self.pushes)


class _StubReply:
    def __init__(self) -> None:
        self.replies: list[str] = []

    async def __call__(self, text: str) -> None:
        self.replies.append(text)


# ──────────────────────────────────────────────────────────────────
# IGNORE
# ──────────────────────────────────────────────────────────────────

async def test_ignore_action_does_nothing():
    mcp, queue, reply = _StubMcp(), _StubQueue(), _StubReply()
    await execute(Action(kind=ActionKind.IGNORE), mcp=mcp, queue=queue, reply_callable=reply)
    assert mcp.calls == []
    assert queue.pushes == []
    assert reply.replies == []


# ──────────────────────────────────────────────────────────────────
# REPLY
# ──────────────────────────────────────────────────────────────────

async def test_reply_action_sends_text():
    mcp, queue, reply = _StubMcp(), _StubQueue(), _StubReply()
    await execute(
        Action(kind=ActionKind.REPLY, reply="hi there"),
        mcp=mcp, queue=queue, reply_callable=reply,
    )
    assert reply.replies == ["hi there"]
    assert mcp.calls == []
    assert queue.pushes == []


async def test_reply_action_with_no_text_is_noop():
    reply = _StubReply()
    await execute(
        Action(kind=ActionKind.REPLY, reply=None),
        mcp=_StubMcp(), queue=_StubQueue(), reply_callable=reply,
    )
    assert reply.replies == []


# ──────────────────────────────────────────────────────────────────
# CAPTURE_TEXT
# ──────────────────────────────────────────────────────────────────

async def test_capture_text_calls_mcp_then_replies():
    mcp, queue, reply = _StubMcp(), _StubQueue(), _StubReply()
    await execute(
        Action(
            kind=ActionKind.CAPTURE_TEXT,
            payload={"content": "thought", "metadata": {"source": "telegram"}},
            reply="✅ saved",
        ),
        mcp=mcp, queue=queue, reply_callable=reply,
    )
    assert mcp.calls == [("thought", {"source": "telegram"})]
    assert reply.replies == ["✅ saved"]


async def test_capture_text_mcp_error_sends_warning_reply():
    mcp, queue, reply = _StubMcp(fail=True), _StubQueue(), _StubReply()
    await execute(
        Action(
            kind=ActionKind.CAPTURE_TEXT,
            payload={"content": "thought"},
            reply="✅ saved",
        ),
        mcp=mcp, queue=queue, reply_callable=reply,
    )
    assert mcp.calls == [("thought", None)]
    # Original "✅ saved" must NOT be sent — only the warning.
    assert reply.replies == ["⚠️ capture failed — check server logs"]


async def test_capture_text_skipped_when_mcp_unconfigured():
    """When the McpClient is missing the action is a no-op rather
    than a crash. Useful for tests that exercise the dispatcher
    alone."""
    queue, reply = _StubQueue(), _StubReply()
    await execute(
        Action(kind=ActionKind.CAPTURE_TEXT, payload={"content": "x"}, reply="✅"),
        mcp=None, queue=queue, reply_callable=reply,
    )
    assert reply.replies == []


# ──────────────────────────────────────────────────────────────────
# ENQUEUE
# ──────────────────────────────────────────────────────────────────

async def test_enqueue_single_pushes_one_job():
    mcp, queue, reply = _StubMcp(), _StubQueue(), _StubReply()
    await execute(
        Action(
            kind=ActionKind.ENQUEUE,
            payload={"queue": "ingest:voice", "job": {"file_id": "v1"}},
            reply="🎙️ transcribing",
        ),
        mcp=mcp, queue=queue, reply_callable=reply,
    )
    assert queue.pushes == [("ingest:voice", {"file_id": "v1"})]
    assert reply.replies == ["🎙️ transcribing"]


async def test_enqueue_batch_pushes_each_item():
    queue, reply = _StubQueue(), _StubReply()
    await execute(
        Action(
            kind=ActionKind.ENQUEUE,
            payload={
                "batch": [
                    {"queue": "ingest:article", "job": {"url": "https://a"}},
                    {"queue": "ingest:youtube", "job": {"url": "https://youtu.be/x"}},
                ],
            },
            reply="🔗 queued 2 url(s)",
        ),
        mcp=_StubMcp(), queue=queue, reply_callable=reply,
    )
    assert [q for q, _ in queue.pushes] == ["ingest:article", "ingest:youtube"]
    assert reply.replies == ["🔗 queued 2 url(s)"]


async def test_enqueue_skipped_when_queue_unconfigured():
    reply = _StubReply()
    await execute(
        Action(
            kind=ActionKind.ENQUEUE,
            payload={"queue": "x", "job": {}},
            reply="queued",
        ),
        mcp=_StubMcp(), queue=None, reply_callable=reply,
    )
    assert reply.replies == []
