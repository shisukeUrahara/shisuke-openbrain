# Python Style Rule

## Versions and tooling

- **Python 3.12+** required across all services.
- **`uv`** is the canonical package manager. No `pip install` outside Docker layers. `uv pip install --system .` inside Dockerfiles is the install pattern.
- **`ruff`** for lint + format. No black, no flake8, no isort. (Configure when introduced.)
- **`pytest` + `pytest-asyncio`** for tests. `asyncio_mode = "auto"` set in `pyproject.toml`.

## Layout

```
services/<service-name>/
├── pyproject.toml
├── Dockerfile
├── .dockerignore
├── src/
│   └── <package>/
│       ├── __init__.py
│       ├── config.py
│       ├── ... .py
│       └── tools/         # plugin-style for MCP
└── tests/
    ├── unit/
    ├── integration/
    └── e2e/        # only when service hosts its own e2e harness
```

Package name = snake_case service name (e.g. `brain_mcp`, `brainstem_bot`, `worker_article`).

## Imports

- Standard library, third-party, local. One blank line between groups.
- No wildcard imports.
- Relative imports inside a package; absolute imports at entry points (`__main__`).

## Type hints

- All public function signatures typed. `from __future__ import annotations` at the top of every file is OK if it simplifies.
- Use `|` union syntax (PEP 604), not `Union[]`.
- `list[int]`, `dict[str, Any]`, not `List`/`Dict`.
- Pydantic models for HTTP request/response shapes.
- `dataclass(frozen=True)` for config-shaped immutables (see `brain_mcp/config.py`).

## Async patterns

- Prefer `async def` for any function that may do I/O, even if currently sync. Easier to call from FastMCP handlers.
- `httpx.AsyncClient` not `requests`.
- `asyncpg` not `psycopg2` for application code. (`psycopg[binary]` is fine for one-off test fixtures.)
- Use the project's `db.conn()` async context manager; do not `await pool.acquire()` directly in tools.
- Time-bounded I/O: every external HTTP call uses an explicit `timeout=` (don't rely on defaults).

## Error handling

- Raise specific exceptions; never bare `except:`.
- Never `except Exception: pass`. If you really need to swallow, log first.
- At HTTP boundaries (MCP tools), translate domain exceptions to JSON-RPC error objects with a meaningful `code` and `message`.
- Auth failures return 401 from the middleware, not from the tool handler.

## Logging

- `logging` stdlib (avoid `print` outside scripts and one-off main blocks).
- Logger name = `__name__`.
- INFO for state transitions, WARNING for retryable issues, ERROR for caller-visible failures.
- Never log secret values (keys, passwords, tokens). Mask if necessary.

## Configuration

- All config is loaded once via `brain_mcp.config.load_config()` (or the analogous loader in each service) and exposed as a frozen object.
- No reading of `os.environ` outside the config loader.
- Defaults live in code; overrides in `config/features.yaml` and `.env`. No surprise defaults from `os.getenv("X", "some-prod-value")`.

## Comments and docstrings

- Default to no comment. The code should explain itself.
- Module-level docstring: one paragraph saying what the file is for.
- Public function docstring: one-line behaviour sentence. Add `Args:` / `Returns:` only when types alone are insufficient.
- Do not write comments that narrate the code (`# loop over items`).
- Comments justify non-obvious choices: workarounds, performance hot spots, security trade-offs.

## Tests (mirrors `python-test-writer` agent)

- Each test docstring states the behaviour, not the mechanics.
- Use the existing `pg` fixture for DB-backed integration tests.
- Mock at the wire (`httpx`), not the function.
- Mark live-API tests with `@pytest.mark.live` so they only run on opt-in.
- Coverage target: core ≥ 80%, modules ≥ 60%.

## Common pitfalls (project-specific)

- `asyncpg` + `pgvector`: pass embeddings as string-literal casts (`'[0.1,0.2,…]'::vector`) unless the codec is registered in `db.py`.
- FastMCP tool functions: the docstring is part of the tool's MCP description — the AI client sees it. Write it for an AI, not a developer.
- Module-gated code: every optional tool is wrapped in `if config.modules.<name>:` at registration time; never at call time.

## When to violate

If you have a concrete reason to break any of the above, write a one-line comment explaining why and add the case to `plan/DECISIONS.md`.
