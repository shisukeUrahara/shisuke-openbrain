# brain-mcp

Python FastMCP server for the self-hosted Open Brain fork. Exposes four core tools (capture, search, browse, stats) over HTTP, talks to Postgres + pgvector, embeds via OpenRouter (or Ollama with `EMBED_PROVIDER=ollama`), and gates every request behind a single bearer key (`BRAIN_KEY`).

Phase 2 of the project. See `plan/PLANNED_PHASES.md` in the repo root.

## Local dev

```bash
docker compose up -d postgres        # from repo root
cd services/mcp-server
uv pip install --system -e ".[dev]"
DATABASE_URL=postgresql://postgres:devpass@localhost:5432/openbrain \
BRAIN_KEY=$(openssl rand -hex 32) \
OPENROUTER_API_KEY=$YOUR_KEY \
python -m brain_mcp.server
```

## Layout

```
src/brain_mcp/
├── config.py        # loads features.yaml + env, exposes frozen Config
├── db.py            # asyncpg pool + conn() context manager
├── embed.py         # OpenRouter / Ollama branches
├── auth.py          # Starlette bearer-key middleware
├── health.py        # GET /health (allowlisted, no auth)
├── server.py        # FastMCP setup + tool registry
└── tools/
    ├── core_capture.py
    ├── core_search.py
    ├── core_browse.py
    └── core_stats.py
```

## Tools

| Tool      | Purpose                                                  |
| --------- | -------------------------------------------------------- |
| `capture` | Embed text, upsert by content fingerprint                |
| `search`  | Hybrid semantic search across `thoughts`                 |
| `browse`  | Recent thoughts chronologically                          |
| `stats`   | Counts + top topics (when modules add topic taxonomy)    |

Optional-module tools (`capture_document`, `add_chunks`, `search_chunks`) register only when `MODULE_DOCUMENTS_ENABLED=true`.
