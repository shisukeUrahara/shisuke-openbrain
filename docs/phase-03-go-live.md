# Phase 3 — Local AI Client Wiring (Operator Guide)

Point an AI client at the local MCP server and exercise the
capture/search loop end to end. Nothing here needs a VPS — it is the
last step you can do entirely on your machine before deployment.

## Prerequisites

```bash
docker compose up -d            # postgres + mcp-server
curl -s http://localhost:8080/health | jq .   # status: ok
set -a; source .env; set +a     # export BRAIN_KEY for the commands below
```

For the capture/search loop (not just `stats`) the server needs an
embedding provider. Set `OPENROUTER_API_KEY` in `.env` and recreate the
mcp-server:

```bash
# .env  ->  OPENROUTER_API_KEY=sk-or-v1-<your-key>
docker compose up -d mcp-server
```

Without a key, capture/search return a 401 from the embedding call —
the e2e test skips that path and the `stats` liveness path still passes.

## Step 1 — Wire Claude Code

```bash
claude mcp add --transport http openbrain-local \
  "http://localhost:8080/mcp?key=$BRAIN_KEY"
```

Note: `/mcp` with **no trailing slash**. A trailing slash triggers a 307
redirect and a "Missing session ID" error with this transport.

Auth works two ways and both are accepted:
- `?key=<BRAIN_KEY>` in the URL (used above — simplest for a CLI), or
- an `x-brain-key: <BRAIN_KEY>` header.

Verify inside Claude Code:

```
/mcp
```

`openbrain-local` should list as healthy. With the default flags you
see the 4 core tools (`capture`, `search`, `browse`, `stats`); with
`MODULE_DOCUMENTS_ENABLED=true` you also see the 3 documents tools, and
with `MODULE_GRAPHIFY_ENABLED=true`, `export_project_corpus`.

## Step 2 — (Optional) Wire Claude Desktop

Claude Desktop connects to remote MCP servers via its connectors UI, not
a config file:

1. Settings → Connectors → **Add custom connector**.
2. URL: `http://localhost:8080/mcp?key=<BRAIN_KEY>`.
3. Save. The brain's tools appear in the composer.

(For a VPS deployment this URL becomes `https://brain.yourdomain.com/mcp?key=…`
— that is Phase 7.)

## Step 3 — Behavioural check

In Claude Code:

> Use openbrain-local to capture: "phase 3 e2e check at 2026-05-24T12:00".

Confirm it landed:

```bash
PGPASSWORD="${POSTGRES_PASSWORD:-devpass}" psql \
  -h localhost -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-openbrain}" \
  -tAc "select content from thoughts where content like 'phase 3 e2e%' order by created_at desc limit 1"
```

A row should come back within a few seconds. Then, in a fresh Claude
Code chat:

> Search openbrain-local for "phase 3 e2e".

It should return the captured thought.

## Step 4 — Automated e2e harness

The same loop, with no human in the loop, lives at
`tests/e2e/test_capture_search_loop.py`:

```bash
set -a; source .env; set +a
docker compose up -d
make test-e2e          # or: scripts/run-tests.sh e2e
```

- `test_stats_tool_is_reachable` — always runs; proves transport + auth.
- `test_capture_then_search_finds_it` — runs the full loop when an
  embedding provider is configured; **skips** (does not fail) when the
  server has no key.

## Local workflow cheat-sheet

| Action | Command |
|---|---|
| Start | `docker compose up -d` |
| Start a module | `docker compose --profile <name> up -d` |
| Stop | `docker compose down` |
| Reset DB (destroys data) | `docker compose down -v && docker compose up -d` |
| Tail server logs | `docker compose logs -f mcp-server` |
| Run all tests | `make test` |
| Run e2e only | `scripts/run-tests.sh e2e` |
| Health | `curl -s localhost:8080/health \| jq` |

## Troubleshooting

| Symptom | Fix |
|---|---|
| `/mcp` shows the connector but no tools | Wrong key, or you used `/mcp/` (trailing slash). Re-add with `/mcp` and the correct `BRAIN_KEY`. |
| "Missing session ID" | Trailing-slash redirect. Use `/mcp` exactly. |
| capture returns a 401 about embeddings | No `OPENROUTER_API_KEY` on the mcp-server. Set it in `.env` and `docker compose up -d mcp-server`. |
| Health is 200 but tools/call 401s | The `x-brain-key`/`?key=` is missing or wrong on the client side. |
| e2e all skipped | `BRAIN_KEY` not exported into the pytest process. `set -a; source .env; set +a` first. |

## Rollback

```bash
claude mcp remove openbrain-local
```
