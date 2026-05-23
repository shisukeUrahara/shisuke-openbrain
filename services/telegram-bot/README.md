# brain-bot — Telegram capture bot

Forwards messages from a single authorized Telegram user into the Open Brain via the MCP server's HTTP surface. Lives behind the `MODULE_TELEGRAM_BOT_ENABLED` flag — when the flag is false the service starts but stays idle (no Telegram polling, no Redis traffic).

Phase 11 of the project. See `plan/PLANNED_PHASES.md`.

## Supported message types

| Telegram type | Handler | Result |
|---|---|---|
| Text without URL | `capture` MCP tool | Stored as a thought, embedded immediately |
| Text containing one or more URLs | Enqueues each URL onto Redis under `ingest:article` or `ingest:youtube` | Picked up by the matching worker in Phase 12 |
| Voice note | Enqueues onto `ingest:voice` | Audio worker transcribes + chunks |
| Photo | Enqueues onto `ingest:image` | Image worker runs OCR + description |
| Document (PDF) | Enqueues onto `ingest:pdf` | PDF worker extracts markdown + chunks |
| Other documents | Ignored with a polite reply | Until a kind-specific worker exists |

## Owner-only enforcement

Every handler checks `m.from_user.id == TELEGRAM_OWNER_ID` before doing any work. Messages from any other user are dropped silently. This is hard-coded — it is not configurable through any tool call — so a hostile chat invite cannot turn the bot into a public capture endpoint.

## Configuration

| Env var | Required when | Purpose |
|---|---|---|
| `MODULE_TELEGRAM_BOT_ENABLED` | always | Master flag. Service idles when false. |
| `TELEGRAM_BOT_TOKEN` | flag on | BotFather token (`/newbot` in Telegram) |
| `TELEGRAM_OWNER_ID` | flag on | Your numeric Telegram user id (`@userinfobot`) |
| `BRAIN_URL` | flag on | Full MCP URL including `?key=`, e.g. `http://mcp-server:8080/mcp?key=...` |
| `REDIS_URL` | flag on | `redis://redis:6379/0` for the dev stack |

When the flag is off, only `MODULE_TELEGRAM_BOT_ENABLED` is read.

## Local dev

```bash
# 1. Build the image
docker compose --profile telegram build telegram-bot

# 2. Add to .env:
MODULE_TELEGRAM_BOT_ENABLED=true
TELEGRAM_BOT_TOKEN=...
TELEGRAM_OWNER_ID=...

# 3. Bring it up
docker compose --profile telegram up -d
docker compose logs -f telegram-bot
```

Send any text to your bot in Telegram. It should reply within ~2 seconds with `✅ saved` (text) or `🔗 queued` (URL) or `📄 queued` (PDF) etc. depending on the handler.

## Layout

```
src/brain_bot/
├── __init__.py
├── config.py        # env loader + module flag check
├── mcp_client.py    # JSON-RPC over HTTP wrapper for capture
├── queue_client.py  # tiny Redis producer wrapper
├── auth.py          # owner-id check
├── handlers.py      # pure functions: classify message -> action
└── server.py        # aiogram Dispatcher wiring + main()
```

`handlers.py` is pure dispatch logic — it returns a typed `Action` instead of doing the side effect itself, so unit tests can exercise classification without aiogram or a real Bot.
