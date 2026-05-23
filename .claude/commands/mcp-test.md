---
description: Smoke-test the MCP server with a curl round-trip. Lists tools, captures, searches.
argument-hint: <local|prod>  (default: local)
---

# /mcp-test

End-to-end check that the MCP server is reachable, authenticated, and the four core tools work.

## Inputs

- `$1` — target environment. `local` (default, hits `http://localhost:8080`) or `prod` (hits `$BRAIN_PROD_URL`).

## Resolution

- Local: `URL=http://localhost:8080/mcp/`, `KEY=$BRAIN_KEY` (from `.env`).
- Prod: `URL=$BRAIN_PROD_URL` (must be exported), `KEY=$BRAIN_KEY`.

If `BRAIN_KEY` is unset, stop and ask the user to source `.env` first.

## Steps

1. **Health check.** `GET <base>/health` → expect `{"ok": true, "modules": {...}}`. Surface which modules are reported as enabled.

2. **List tools.**
   ```bash
   curl -s -X POST "$URL?key=$BRAIN_KEY" \
     -H 'Content-Type: application/json' \
     -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' | jq -r '.result.tools[].name'
   ```
   Expected core tools: `capture`, `search`, `browse`, `stats`. If `MODULE_DOCUMENTS_ENABLED=true`, also `capture_document`, `add_chunks`, `search_chunks`.

3. **Unauth check.** Same call with `?key=wrong` → expect HTTP `401`.

4. **Capture round-trip.**
   - Generate a UUID-tagged content string: `mcp-test-<short-uuid>`.
   - Call `tools/call` → `capture`. Expect `{ id, fingerprint }`.
   - Wait ~200ms.
   - Call `tools/call` → `search` with the UUID tag as query. Expect ≥ 1 hit containing the tag.

5. **Stats sanity.** Call `stats`. Expect `total_thoughts ≥ 1`.

6. **Report.**
   - ✅ all five checks pass → MCP server is healthy.
   - ❌ any check fails → quote the failing response body verbatim and propose the most likely cause:
     - 401 on right key → middleware bug or stale env var
     - empty tools list → registry not wiring tools
     - capture works but search empty → embedding silently failing
     - timeouts → container down or wrong port

## Output style

Terse table:

```
✓ health
✓ tools/list (4)
✓ 401 on wrong key
✓ capture id=<uuid>
✓ search found 1 hit
✓ stats total=42
```
