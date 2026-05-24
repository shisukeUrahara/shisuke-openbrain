# Phase 6 — Deploy MCP Server to VPS (Operator Guide)

Deploy the same image you run locally to Coolify, behind a Let's Encrypt
TLS cert, reachable at `https://brain.yourdomain.com/mcp`.

**Prerequisites:** Phase 5 (Coolify + `PROD_DATABASE_URL`), repo pushed
to GitHub, DNS A record from Phase 4 resolving.

## What gets deployed

`services/mcp-server/Dockerfile` — already prod-shaped: `python:3.12-slim`,
deps via `uv pip install --system`, a `/health` HEALTHCHECK, exposes
`8080`, runs `python -m brain_mcp.server`. This is byte-for-byte the
image `docker compose` builds locally, so "works on my machine" and
"works in prod" are the same artifact.

## Step 1 — Push

```bash
git push origin main
```

If the repo is private, add a Coolify deploy key (Coolify → Sources) or
a GitHub App connection so it can pull.

## Step 2 — New Application in Coolify

- **New Resource → Application → from your Git repo.**
- Build Pack: **Dockerfile**
- Dockerfile path: `services/mcp-server/Dockerfile`
- Base directory: `services/mcp-server`
- Port: `8080`

## Step 3 — Environment variables

Set these on the application (Coolify → app → Environment Variables). See
the full checklist in `docs/phase-06-env-checklist.md`.

| Var | Value | Notes |
|---|---|---|
| `DATABASE_URL` | `$PROD_DATABASE_URL` | Internal container DSN from Phase 5 Step 5 — **not** the SSH-tunnel DSN. |
| `BRAIN_KEY` | your 32-byte hex key | Same one your clients use. Generate with `openssl rand -hex 32`. |
| `OPENROUTER_API_KEY` | `sk-or-v1-…` | Needed for capture/search (embeddings). |
| `EMBED_PROVIDER` | `openrouter` | |
| `MODULE_*_ENABLED` | `false` | Start with every module off; enable per its go-live doc later. |

## Step 4 — Domain + TLS

Set the application domain to `https://brain.yourdomain.com`. Coolify
requests a Let's Encrypt certificate automatically. If issuance fails,
DNS likely hasn't propagated — wait, then redeploy.

## Step 5 — Deploy + verify

Click **Deploy**, wait for **Healthy**, then from your laptop:

```bash
curl -s https://brain.yourdomain.com/health | jq .
# -> {"ok": true, "version": "...", "embed_provider": "openrouter", "modules": {...}}

set -a; source .env; set +a   # BRAIN_KEY
curl -s -X POST "https://brain.yourdomain.com/mcp" \
  -H "x-brain-key: $BRAIN_KEY" \
  -H 'Content-Type: application/json' -H 'Accept: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \
  | jq -r '.result.tools | length'      # -> 4 (all modules off)
```

## Step 6 — Production e2e suite

Run the committed black-box prod smoke against the live deployment:

```bash
BRAIN_URL=https://brain.yourdomain.com/mcp BRAIN_KEY=$BRAIN_KEY \
  python3 -m pytest tests/e2e/test_prod_smoke.py -v
```

It asserts: HTTPS, `/health.ok == true`, the 4 core tools present, a
wrong key is rejected with 401, and the capture→search loop round-trips
(this last one skips if `OPENROUTER_API_KEY` is not set on the server).

## Acceptance criteria

- Green padlock at `https://brain.yourdomain.com/health` in a browser.
- `tests/e2e/test_prod_smoke.py` passes (capture/search may skip without
  a server-side embedding key).
- Coolify status = Healthy.

## Troubleshooting

| Symptom | Fix |
|---|---|
| LE cert won't issue | DNS not propagated. `dig +short brain.yourdomain.com` must show the VPS IP. Wait, redeploy. |
| App healthy but `/mcp` 401s | `BRAIN_KEY` mismatch between the app env and your client. |
| App can't reach the DB | `DATABASE_URL` is the tunnel DSN, not the internal container DSN from Phase 5 Step 5. |
| `tools/list` returns more than 4 | A `MODULE_*_ENABLED` is `true`. Expected once you enable modules; the prod test uses `>= 4` so it stays green. |
| capture 401s on embeddings | `OPENROUTER_API_KEY` missing on the app. Add it, redeploy. |

## Rollback

Coolify → app → Deployments → pick the last good deploy → **Rollback**.
