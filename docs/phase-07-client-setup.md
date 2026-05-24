# Phase 7 — Wire AI Clients to the Production Brain (Operator Guide)

Every client connects to the **same** HTTP MCP endpoint with the **same**
bearer key. One brain, many clients — capture from any, search from any.

**Prerequisite:** Phase 6 — server live at `https://brain.yourdomain.com`.

## Validate the endpoint first

Before fighting any client UI, prove the URL works:

```bash
scripts/check-client-endpoint.sh https://brain.yourdomain.com/mcp "$BRAIN_KEY"
# -> /health ok, tools/list >= 4 incl. core, wrong key -> 401, "endpoint OK"
```

If that exits 0, every client below will connect. If it fails, fix the
server (Phase 6 troubleshooting) before touching clients.

## The one rule: no trailing slash

Use `https://brain.yourdomain.com/mcp` — **never** `/mcp/`. The
streamable-http transport 307-redirects on the trailing slash and
clients then fail with "Missing session ID". This is the single most
common wiring mistake.

Auth is by bearer key, two interchangeable forms:
- header `x-brain-key: <BRAIN_KEY>`, or
- query `?key=<BRAIN_KEY>` (handy for clients that only take a URL).

## 7.1 Claude Code

```bash
claude mcp add --transport http openbrain \
  "https://brain.yourdomain.com/mcp?key=$BRAIN_KEY"

claude mcp list        # openbrain -> healthy
```

In a session, `/mcp` lists the server and its tools. Remove with
`claude mcp remove openbrain`.

## 7.2 Claude Desktop

1. Settings → **Connectors** → **Add custom connector**.
2. URL: `https://brain.yourdomain.com/mcp?key=<BRAIN_KEY>`.
3. Save. The brain's tools appear in the composer's tools menu.

(Claude Desktop has no env for headers, so the `?key=` form is the way.)

## 7.3 ChatGPT (Plus/Pro)

1. Settings → **Apps & Connectors** → enable **Developer Mode**.
2. **Add Custom Connector** → paste `https://brain.yourdomain.com/mcp?key=<BRAIN_KEY>`.

> **Trade-off:** enabling Developer Mode disables ChatGPT's built-in
> Memory feature. You're replacing ChatGPT's memory with the brain. Log
> this in `plan/DECISIONS.md` if it matters to you.

## 7.4 Cursor

1. Settings → **MCP** → **Add new MCP server**.
2. Type: HTTP. URL: `https://brain.yourdomain.com/mcp?key=<BRAIN_KEY>`.
3. Save; Cursor shows the tools under the server once connected.

## 7.5 Cross-client behavioural test

The real proof is that the clients share one memory:

1. In **Claude Desktop**: "Capture to openbrain: 'cross-client check
   alpha-7'."
2. In **Claude Code** (different client, same brain): "Search openbrain
   for 'alpha-7'." → it returns the thought captured by Desktop.
3. Reverse it: capture from ChatGPT, search from Claude Desktop.

If a captured thought is findable from a *different* client, the brain
is wired correctly.

## Acceptance criteria

- `scripts/check-client-endpoint.sh <prod-url> $BRAIN_KEY` exits 0.
- Each wired client lists at least the 4 core tools.
- A thought captured in one client is found by searching from another.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Client shows the server but no tools | Wrong key, or a `/mcp/` trailing slash. Re-validate with the script. |
| "Missing session ID" | Trailing slash. Use `/mcp`. |
| ChatGPT lost its memory | Expected — Developer Mode disables built-in Memory. |
| Tools appear but capture errors | Server lacks `OPENROUTER_API_KEY` (embeddings). See Phase 6 env checklist. |
| Cross-client search finds nothing | The two clients point at different URLs/keys, or capture failed silently. Validate both clients' URLs with the script. |

## Rollback

Remove the connector per client (Claude Code: `claude mcp remove openbrain`;
others: delete the connector in settings).
