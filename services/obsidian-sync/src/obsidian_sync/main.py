"""Obsidian-sync entry point.

On startup (when enabled):
  1. Connect to Postgres.
  2. Backfill sweep — write any document missing from the vault.
  3. LISTEN on new_document; write each new document as it arrives.

Idle mode (flag off) sleeps forever, same pattern as the workers.

File writes go through write_note(), which is the only impure seam;
render.render_note() does the pure path + content building so it is
unit-tested separately.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any

import asyncpg

from . import db
from .config import Config, load_config
from .render import RenderedNote, render_note


logger = logging.getLogger("obsidian_sync")


def write_note(vault_dir: Path, note: RenderedNote, *, overwrite: bool = True) -> bool:
    """Write a rendered note under vault_dir. Returns True if a file
    was written, False if it already existed and overwrite is False.

    The join is guarded: render.safe_segment forbids traversal tokens,
    and we re-assert the resolved path stays inside the vault."""
    target = (vault_dir / note.relative_path).resolve()
    vault_resolved = vault_dir.resolve()
    if not str(target).startswith(str(vault_resolved) + os.sep):
        raise ValueError(f"refusing to write outside vault: {target}")

    if target.exists() and not overwrite:
        return False
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(note.text, encoding="utf-8")
    return True


async def backfill(conn: asyncpg.Connection, vault_dir: Path) -> int:
    """Write any document not already present in the vault. Returns
    the number of files newly written."""
    written = 0
    async for doc in db.iter_all_documents(conn):
        note = render_note(doc)
        if write_note(vault_dir, note, overwrite=False):
            written += 1
    logger.info("backfill complete: %d new note(s) written", written)
    return written


async def handle_notification(conn: asyncpg.Connection, vault_dir: Path, payload: str) -> None:
    """Process one new_document NOTIFY payload."""
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logger.warning("ignoring malformed notify payload: %r", payload)
        return
    doc_id = data.get("id")
    if not doc_id:
        logger.warning("notify payload missing id: %r", payload)
        return
    doc = await db.fetch_document(conn, str(doc_id))
    if doc is None:
        logger.warning("document %s vanished before mirror could read it", doc_id)
        return
    note = render_note(doc)
    write_note(vault_dir, note, overwrite=True)
    logger.info("mirrored document %s -> %s", doc_id, note.relative_path)


async def run(config: Config) -> None:
    vault_dir = Path(config.vault_dir)
    vault_dir.mkdir(parents=True, exist_ok=True)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    # A bare LISTEN connection that sits idle eventually stops
    # delivering notifications (TCP idle drop, server-side timeout,
    # or asyncpg's reader stalling). asyncpg does NOT auto-reconnect.
    # So we run a supervised loop: connect, backfill any gap, LISTEN,
    # then poll a cheap keepalive every KEEPALIVE_S. If the keepalive
    # raises, the connection is dead — we reconnect, which re-runs the
    # backfill sweep to catch anything missed while we were down.
    keepalive_s = 30
    backfill_done_once = False

    while not stop.is_set():
        conn = None
        try:
            conn = await db.connect(config.database_url)

            # Backfill on first connect (if enabled) and after every
            # reconnect — the sweep is overwrite=false so it is cheap
            # when nothing is missing.
            if config.backfill_on_start or backfill_done_once:
                await backfill(conn, vault_dir)
            backfill_done_once = True

            def _on_notify(_conn, _pid, _channel, payload):
                asyncio.create_task(handle_notification(conn, vault_dir, payload))

            await conn.add_listener("new_document", _on_notify)
            logger.info("listening on new_document, vault=%s", vault_dir)

            # Keepalive loop — also our liveness probe for the
            # LISTEN connection.
            while not stop.is_set():
                try:
                    await asyncio.wait_for(stop.wait(), timeout=keepalive_s)
                except asyncio.TimeoutError:
                    pass  # normal: time to send a keepalive
                if stop.is_set():
                    break
                await conn.execute("SELECT 1")  # raises if the conn died

        except (asyncpg.PostgresError, OSError) as exc:
            logger.warning("listen connection lost (%s); reconnecting in 5s", exc)
            await asyncio.sleep(5)
        finally:
            if conn is not None:
                try:
                    await conn.close()
                except Exception:
                    pass


async def _idle_forever() -> None:
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
            "MODULE_OBSIDIAN_MIRROR_ENABLED is false — obsidian-sync is idle. "
            "Set the flag to true and restart to start mirroring."
        )
        asyncio.run(_idle_forever())
        return

    try:
        config = load_config(require_runtime=True)
    except RuntimeError as exc:
        logger.error("refusing to start: %s", exc)
        sys.exit(2)

    asyncio.run(run(config))


if __name__ == "__main__":
    main()
