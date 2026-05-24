# Phase 9 — Production Hardening Baseline (Operator Guide)

Make the system safe to leave unattended: rate limiting, secret
hygiene, Postgres tuning, and disk hygiene.

**Prerequisite:** Phase 6 (server live).

## 9.1 Secret hygiene

**Scan history** for any leaked secret before going public:

```bash
scripts/scan-history-secrets.sh    # exit 0 = clean
```

It greps every commit's additions for this project's real secret shapes
(`sk-or-v1-…`, hex `BRAIN_KEY=…`, generic 64-char `*_KEY/_SECRET/_TOKEN`).
A hit means: rotate the secret, then consider rewriting history with
`git filter-repo` before the repo is public.

**Rotate-key drill** (do it once so you know the steps under pressure):

1. Generate a new key: `openssl rand -hex 32`.
2. Coolify → app → Environment → set `BRAIN_KEY` to the new value → redeploy.
3. Update every client (Phase 7) to the new key.
4. Confirm: the **old** key now returns 401, the **new** key works.

```bash
# old key -> 401
curl -s -o /dev/null -w '%{http_code}\n' -X POST https://brain.yourdomain.com/mcp \
  -H "x-brain-key: $OLD_KEY" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
# new key -> tools
scripts/check-client-endpoint.sh https://brain.yourdomain.com/mcp "$NEW_KEY"
```

## 9.2 Rate limiting

Built into the MCP server as `RateLimitMiddleware` — a per-IP sliding
window, on by default, **100 req/min/IP**, sitting *outside* auth so a
flood is rejected with 429 before it can burn auth cycles. `/health` is
exempt so uptime monitors are never throttled.

Configure via env (wired through docker-compose / Coolify):

| Var | Default | Effect |
|---|---|---|
| `RATE_LIMIT_ENABLED` | `true` | Master switch |
| `RATE_LIMIT_PER_MIN` | `100` | Requests per IP per 60s before 429 |

Behind Coolify's proxy the client IP is read from `X-Forwarded-For`
(first hop), falling back to the socket peer.

Verify locally:

```bash
RATE_LIMIT_PER_MIN=5 docker compose up -d mcp-server
for i in $(seq 1 7); do
  curl -s -o /dev/null -w "%{http_code} " -X POST http://localhost:8080/mcp \
    -H "x-brain-key: $BRAIN_KEY" -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
done; echo
# -> 200 200 200 200 200 429 429
docker compose up -d mcp-server   # restore the default
```

> **Note:** the counter is in-memory, so the limit is per-process. That
> is correct for this fork's single-instance deployment. To run multiple
> replicas, move the counter to Redis (the workers already pull in a
> Redis dependency); the middleware is intentionally small so that swap
> is a local change.

Load test (the acceptance criterion):

```bash
hey -n 1000 -c 20 https://brain.yourdomain.com/health   # no error spike
# /mcp past the threshold should start returning 429
```

## 9.3 Postgres tuning

Apply `config/postgresql.tuning.conf` to the Coolify DB resource
(Configuration → custom postgresql.conf), then restart. Values are sized
for the 4 GB Phase 4 box: `shared_buffers=256MB`, `work_mem=16MB`,
`maintenance_work_mem=64MB`, plus SSD-friendly `random_page_cost=1.1`
and an `effective_cache_size` that nudges the planner toward index scans.

Confirm the HNSW vector index is actually used afterward:

```bash
DATABASE_URL=<prod-or-tunnel-dsn> scripts/check-index-usage.sh
# -> "match query uses the HNSW embedding index"
```

It needs ~50+ embedded rows for the planner to prefer the index (on a
tiny table a seq scan is genuinely cheaper, and the script skips rather
than failing).

## 9.4 Disk hygiene

Docker image churn from redeploys fills the disk over weeks. Add a
weekly prune cron on the VPS:

```bash
# /etc/cron.weekly/docker-prune  (chmod +x, run as root)
#!/usr/bin/env bash
docker system prune -a -f --filter "until=168h"
```

Keep `df -h /` under 70%. If it creeps up between prunes, the usual
culprit is accumulated backups or n8n execution history (set a pruning
policy in n8n settings).

## Acceptance criteria

- `scripts/scan-history-secrets.sh` exits 0.
- Rotate-key drill: old key → 401, new key → works.
- Rate limiter trips to 429 past the threshold on `/mcp`; `/health`
  never throttled.
- `scripts/check-index-usage.sh` shows the HNSW index used (against a
  populated DB).
- `df -h /` under 70%.
