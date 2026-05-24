# Phase 14 — n8n Scheduler Go-Live (Operator Guide)

n8n gives you scheduled workflows that call the brain and deliver or capture results. Two templates ship: a daily digest and a weekly review.

## Step 1 — Enable + start

```bash
grep -q '^MODULE_N8N_SCHEDULER_ENABLED=' .env \
  && sed -i 's|^MODULE_N8N_SCHEDULER_ENABLED=.*$|MODULE_N8N_SCHEDULER_ENABLED=true|' .env \
  || echo 'MODULE_N8N_SCHEDULER_ENABLED=true' >> .env

# Generate a STABLE encryption key — changing it later makes stored
# credentials unreadable.
grep -q '^N8N_ENCRYPTION_KEY=' .env || echo "N8N_ENCRYPTION_KEY=$(openssl rand -hex 32)" >> .env

# Set editor auth (do not leave the default in production).
cat >> .env <<'ENV'
N8N_BASIC_AUTH_USER=admin
N8N_BASIC_AUTH_PASSWORD=<pick-a-strong-one>
ENV

docker compose --profile n8n up -d n8n
```

n8n stores its workflows + credentials + execution history in the shared Postgres under a dedicated `n8n` schema — it never touches your `thoughts`/`documents` tables.

## Step 2 — Open the editor

Browser → `http://localhost:5678` (prod: `https://n8n.yourdomain.com`). Log in with the basic-auth credentials. First launch also asks you to create an n8n owner account.

## Step 3 — Add the OpenRouter credential

The workflows summarize via OpenRouter. Add the credential once:

1. Editor → Credentials → New → **Header Auth**.
2. Name: `OpenRouter`.
3. Header name: `Authorization`. Header value: `Bearer sk-or-v1-<your-key>`.
4. Save.

## Step 4 — Import the workflows

For each of `daily-digest.json` and `weekly-review.json`:

1. Editor → top-right `⋯` → **Import from File**.
2. The templates are mounted in the container at `/workflows/`. From your host they live in `services/n8n/workflows/`. Pick the file.
3. Open the **Summarize via OpenRouter** node → set its credential to the `OpenRouter` credential from Step 3.
4. Confirm the two brain-calling HTTP nodes read `{{ $env.BRAIN_URL }}` — that env var is injected by docker-compose and already contains `?key=<BRAIN_KEY>`.
5. **Save**, then toggle **Active**.

## Step 5 — Test a run immediately

Do not wait for the cron. In the editor, open the workflow and click **Execute Workflow** (it runs the trigger manually). Watch each node light up green. The final node should `capture` the digest back into the brain.

Verify:

```bash
PGPASSWORD=devpass psql -h localhost -U postgres -d openbrain -tAc \
  "SELECT content FROM thoughts WHERE metadata->>'type' IN ('daily_digest','weekly_review') ORDER BY created_at DESC LIMIT 1"
```

You should see the generated digest text. That digest is now itself searchable — the compounding loop.

## Step 6 — (Optional) Deliver to Telegram

Append a Telegram node after the summarize node:

1. Add node → **Telegram** → Send Message.
2. Credential: a Telegram API credential with your bot token.
3. Chat ID: your numeric Telegram id.
4. Text: `={{ $json.choices[0].message.content }}`.

Now the digest both saves to the brain AND pings your phone.

## Schedules

| Workflow | Cron | When |
|---|---|---|
| Daily Digest | `0 22 * * *` | 22:00 every day |
| Weekly Review | `0 8 * * 1` | 08:00 every Monday |

Edit the Schedule Trigger node to change times. n8n uses the `GENERIC_TIMEZONE` env (default UTC) — set `TZ` in `.env` for local time.

## Configuration

| Env var | Default | Purpose |
|---|---|---|
| `MODULE_N8N_SCHEDULER_ENABLED` | false | Master flag |
| `N8N_ENCRYPTION_KEY` | (placeholder) | **Set a real one.** Encrypts stored credentials. |
| `N8N_BASIC_AUTH_USER` / `_PASSWORD` | admin / changeme | Editor login — change these |
| `N8N_HOST` / `N8N_PROTOCOL` / `N8N_PORT` | localhost / http / 5678 | Public-facing settings for prod |
| `BRAIN_URL` | (compose default) | Full MCP URL with `?key=` the workflows call |
| `TZ` | UTC | Timezone for cron schedules |

## Troubleshooting

| Symptom | Fix |
|---|---|
| Editor won't load | Check `docker compose --profile n8n logs n8n`. Most boot failures are a bad `DB_POSTGRESDB_*` value. |
| "credentials could not be decrypted" after restart | `N8N_ENCRYPTION_KEY` changed between runs. Set it once and keep it stable; re-enter credentials if it was rotated. |
| HTTP node to brain returns 401 | `BRAIN_URL` missing the `?key=` or the key is wrong. It is injected from `BRAIN_KEY` in `.env` — confirm both are set. |
| Summarize node 401 | OpenRouter credential header value must be `Bearer sk-or-...` (include "Bearer "). |
| Workflow runs but nothing captured | The final HTTP node's JSON body must reference `$json.choices[0].message.content`. Check the OpenRouter response shape in the node's output panel. |

## Notes

- The committed workflow JSON carries **no secrets** — credentials are attached in the editor and stored encrypted in the `n8n` schema.
- n8n's own execution history accumulates in Postgres. Set an execution-data pruning policy in n8n settings if it grows.
