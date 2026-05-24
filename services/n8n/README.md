# n8n scheduler

n8n is the project's control plane for scheduled workflows — nightly digests, weekly reviews, and any other "run on a cron, call the brain, deliver somewhere" automation. It runs as a stock n8n container (no custom code) behind the `n8n` profile and `MODULE_N8N_SCHEDULER_ENABLED`.

Phase 14.

## Why n8n instead of Python cron jobs

The ingestion workers are code because they do heavy, testable transforms. Scheduled syntheses are different: they are mostly "hit an endpoint, pass the result to an LLM, deliver the summary." That is faster to draft and tweak in n8n's visual editor than as Python, and the workflows live as JSON you can version here.

## What ships

`workflows/` holds importable workflow templates:

| File | Schedule | What it does |
|---|---|---|
| `daily-digest.json` | 22:00 daily | Browse the day's captures → summarize via OpenRouter → capture the digest back + (optional) deliver to Telegram |
| `weekly-review.json` | Mon 08:00 | Browse the week's captures → synthesize themes + open threads → capture the review back |

These are **starting points**. n8n's import expects you to re-attach credentials (the brain URL+key, the OpenRouter key, the Telegram chat) through its UI — secrets never live in the committed JSON.

## How it connects to the brain

Workflows call the MCP server over HTTP exactly like any other client:

```
POST http://mcp-server:8080/mcp?key=<BRAIN_KEY>
{"jsonrpc":"2.0","id":1,"method":"tools/call",
 "params":{"name":"browse","arguments":{"since_days":1,"limit":50}}}
```

and capture results back with `{"name":"capture","arguments":{"content":"...","metadata":{"type":"daily_digest"}}}`.

n8n stores its own state (workflow definitions, execution history, credentials) in Postgres under a dedicated `n8n` schema so it shares the database resource without colliding with the `thoughts`/`documents` tables.

## Configuration

| Env var | Required when | Purpose |
|---|---|---|
| `MODULE_N8N_SCHEDULER_ENABLED` | always | Master flag (gates the compose profile in practice) |
| `N8N_ENCRYPTION_KEY` | flag on | Encrypts stored credentials; generate with `openssl rand -hex 32` |
| `N8N_HOST` | optional | Hostname n8n is served at (prod) |
| `N8N_PORT` | optional | Default 5678 |
| `N8N_BASIC_AUTH_USER` / `N8N_BASIC_AUTH_PASSWORD` | recommended | Protect the editor UI |

## Local dev

```bash
docker compose --profile n8n up -d n8n
# editor at http://localhost:5678
```

Import a workflow: editor → top-right menu → Import from File → pick `services/n8n/workflows/daily-digest.json` → open each HTTP node and set the brain URL + key → set the OpenRouter credential → Save → Activate.

See `docs/phase-14-go-live.md` for the full walkthrough.
