#!/usr/bin/env bash
# Validate an MCP endpoint URL before you paste it into a client.
#
# Every client in Phase 7 (Claude Code, Claude Desktop, ChatGPT, Cursor)
# connects to the same HTTP MCP endpoint with the same bearer key. This
# script exercises exactly what a client does on connect, so you can
# confirm a URL works *before* fighting a client's UI:
#
#   1. /health is 200 and {"ok": true}
#   2. tools/list with the key returns >= 4 tools incl. the 4 core ones
#   3. tools/list with a wrong key is rejected (401)
#
# Usage:
#   scripts/check-client-endpoint.sh https://brain.example.com/mcp <BRAIN_KEY>
#   BRAIN_URL=... BRAIN_KEY=... scripts/check-client-endpoint.sh
set -uo pipefail

url="${1:-${BRAIN_URL:-}}"
key="${2:-${BRAIN_KEY:-}}"

if [ -z "$url" ] || [ -z "$key" ]; then
  echo "usage: $0 <mcp-url> <brain-key>   (or set BRAIN_URL/BRAIN_KEY)" >&2
  exit 2
fi

# Strip a trailing slash — the streamable-http transport 307-redirects
# on /mcp/ and clients then error with "Missing session ID".
case "$url" in
  */) echo "warning: trailing slash on URL — clients should use it without"
      url="${url%/}" ;;
esac

# Derive the sibling /health path on the same origin.
base="${url%%\?*}"
base="${base%/mcp}"
health="${base%/}/health"

fail=0
note() { printf "  %s %s\n" "$1" "$2"; }

echo "==> endpoint: ${url%%\?*}"

code=$(curl -s -o /tmp/_ce_health.$$ -w '%{http_code}' "$health" 2>/dev/null || echo 000)
if [ "$code" = "200" ] && grep -q '"ok"[[:space:]]*:[[:space:]]*true' /tmp/_ce_health.$$ 2>/dev/null; then
  note "✓" "/health is 200 and ok=true"
else
  note "✗" "/health failed (http=$code)"; fail=1
fi
rm -f /tmp/_ce_health.$$

tools=$(curl -s -X POST "$url" \
  -H "x-brain-key: $key" \
  -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' 2>/dev/null | sed 's/^data: //')

missing=$(printf '%s' "$tools" | jq -r \
  '[.result.tools[].name] as $n | ((["capture","search","browse","stats"] - $n) | length)' 2>/dev/null || echo "ERR")
count=$(printf '%s' "$tools" | jq -r '.result.tools | length' 2>/dev/null || echo "ERR")

if [ "$missing" = "0" ] && [ "$count" != "ERR" ] && [ "$count" -ge 4 ] 2>/dev/null; then
  note "✓" "tools/list returns $count tools incl. the 4 core"
else
  note "✗" "tools/list missing core tools or unparseable (missing=$missing count=$count)"; fail=1
fi

bad=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$url" \
  -H "x-brain-key: definitely-wrong" \
  -H 'Content-Type: application/json' -H 'Accept: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' 2>/dev/null || echo 000)
if [ "$bad" = "401" ]; then
  note "✓" "wrong key rejected with 401"
else
  note "✗" "wrong key NOT rejected (http=$bad) — auth misconfigured"; fail=1
fi

if [ "$fail" -eq 0 ]; then
  echo "==> endpoint OK — safe to paste into a client"
  exit 0
else
  echo "==> endpoint has problems — fix before wiring clients" >&2
  exit 1
fi
