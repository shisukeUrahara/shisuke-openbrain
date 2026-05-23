"""Aiogram wiring + main entry point.

The module is intentionally thin: it normalises an aiogram Message
into our internal shape, asks `handlers.dispatch` for an Action,
then executes that Action against the configured side-effect clients.
All decision logic lives in handlers.py, all I/O lives here.

When MODULE_TELEGRAM_BOT_ENABLED is false the entry point logs
"disabled, idle" and sleeps forever rather than crashing. That keeps
docker-compose lifecycles predictable when a module is parked.
"""
from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

from .config import Config, load_config
from .handlers import Action, ActionKind, NormalizedMessage, dispatch
from .mcp_client import McpClient, McpError
from .queue_client import QueueClient


logger = logging.getLogger("brain_bot")


def to_normalized(msg) -> NormalizedMessage:  # type: ignore[no-untyped-def]
    """Project an aiogram Message into our handler-friendly shape."""
    voice = getattr(msg, "voice", None)
    photo_list = getattr(msg, "photo", None)  # list[PhotoSize] sorted small->large
    photo = photo_list[-1] if photo_list else None
    document = getattr(msg, "document", None)

    return NormalizedMessage(
        user_id=msg.from_user.id if msg.from_user else 0,
        message_id=msg.message_id,
        text=getattr(msg, "text", None) or getattr(msg, "caption", None),
        voice_file_id=voice.file_id if voice else None,
        voice_duration_s=voice.duration if voice else None,
        photo_file_id=photo.file_id if photo else None,
        photo_caption=getattr(msg, "caption", None),
        document_file_id=document.file_id if document else None,
        document_file_name=document.file_name if document else None,
        document_mime_type=document.mime_type if document else None,
    )


async def execute(
    action: Action,
    *,
    mcp: McpClient | None,
    queue: QueueClient | None,
    reply_callable,
) -> None:
    """Perform the side effects implied by an Action.

    `reply_callable` is an async function `(text: str) -> None` —
    server.py wires this to the aiogram Message.reply method, tests
    can substitute a simple async lambda.
    """
    if action.kind == ActionKind.IGNORE:
        return

    if action.kind == ActionKind.REPLY:
        if action.reply:
            await reply_callable(action.reply)
        return

    if action.kind == ActionKind.CAPTURE_TEXT:
        if mcp is None:
            logger.warning("capture skipped: McpClient is unconfigured")
            return
        try:
            await mcp.capture(
                content=action.payload["content"],
                metadata=action.payload.get("metadata"),
            )
        except McpError as exc:
            logger.error("capture failed: %s", exc)
            await reply_callable("⚠️ capture failed — check server logs")
            return
        if action.reply:
            await reply_callable(action.reply)
        return

    if action.kind == ActionKind.ENQUEUE:
        if queue is None:
            logger.warning("enqueue skipped: QueueClient is unconfigured")
            return
        # Two payload shapes: single {queue, job} or {batch: [...]}.
        items = action.payload.get("batch") or [action.payload]
        for item in items:
            await queue.enqueue(item["queue"], item["job"])
        if action.reply:
            await reply_callable(action.reply)
        return

    logger.warning("unhandled action kind: %s", action.kind)


async def run(config: Config) -> None:
    """Start polling. Only invoked when config.enabled is True."""
    # Imported lazily so disabled-mode does not need aiogram installed.
    from aiogram import Bot, Dispatcher, F  # type: ignore[import-not-found]
    from aiogram.types import Message  # type: ignore[import-not-found]

    bot = Bot(token=config.bot_token)
    dispatcher = Dispatcher()
    mcp = McpClient(config.brain_url)
    queue = QueueClient(config.redis_url)

    @dispatcher.message(F.text | F.voice | F.photo | F.document)
    async def on_message(message: Message) -> None:  # type: ignore[no-untyped-def]
        normalized = to_normalized(message)
        action = dispatch(normalized, owner_id=config.owner_id)
        await execute(
            action,
            mcp=mcp,
            queue=queue,
            reply_callable=message.reply,
        )

    logger.info(
        "starting Telegram polling (owner=%d, brain_url=%s)",
        config.owner_id,
        # Mask anything after `?key=` so the key never appears in logs.
        config.brain_url.split("?", 1)[0] + ("?key=…" if "?key=" in config.brain_url else ""),
    )
    try:
        await dispatcher.start_polling(bot)
    finally:
        await queue.close()
        await bot.session.close()


async def _idle_forever() -> None:
    """Sleep forever so docker-compose keeps the container running
    when the module is parked. Reacts to SIGTERM by exiting cleanly."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    await stop.wait()


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    config = load_config(require_runtime=False)
    if not config.enabled:
        logger.info(
            "MODULE_TELEGRAM_BOT_ENABLED is false — service is idle. "
            "Set the flag to true and restart to start polling."
        )
        asyncio.run(_idle_forever())
        return

    # Re-load with runtime validation enabled now that we know we want
    # to actually run.
    try:
        config = load_config(require_runtime=True)
    except RuntimeError as exc:
        logger.error("refusing to start: %s", exc)
        sys.exit(2)

    asyncio.run(run(config))


if __name__ == "__main__":
    main()
