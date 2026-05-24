#!/usr/bin/env bats
# Phase 9 smoke — rate limiting on the live local stack + the history
# secret scan. The middleware is the same one that runs in production.
#
# Prereqs:
#   set -a; source .env; set +a
#   RATE_LIMIT_PER_MIN=3 docker compose up -d mcp-server
#
# Run:
#   bats tests/smoke/phase-09.bats

setup() {
  : "${BRAIN_KEY:?BRAIN_KEY must be exported}"
  URL="http://localhost:8080"
  if [ "$(curl -s -o /dev/null -w '%{http_code}' "$URL/health")" != "200" ]; then
    skip "mcp-server not reachable (docker compose up -d)"
  fi
  LIMIT="$(docker compose exec -T mcp-server printenv RATE_LIMIT_PER_MIN 2>/dev/null || echo 100)"
}

mcp_code() {
  curl -s -o /dev/null -w '%{http_code}' -X POST "$URL/mcp" \
    -H "x-brain-key: $BRAIN_KEY" \
    -H 'Content-Type: application/json' -H 'Accept: application/json' \
    -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
}

@test "history is free of leaked secrets" {
  run bash scripts/scan-history-secrets.sh
  [ "$status" -eq 0 ]
  [[ "$output" == *"history clean"* ]]
}

@test "rate limiter eventually returns 429 when flooded" {
  # Fire well past any reasonable test limit and require at least one 429.
  saw=0
  for _ in $(seq 1 $((LIMIT + 5))); do
    [ "$(mcp_code)" = "429" ] && { saw=1; break; }
  done
  # Only meaningful when the server was started with a small limit; if
  # the limit is the default 100, this loop won't reach it — skip then.
  if [ "$LIMIT" -gt 50 ]; then
    skip "limit is $LIMIT; start with RATE_LIMIT_PER_MIN=3 to exercise 429"
  fi
  [ "$saw" -eq 1 ]
}

@test "/health is never rate limited" {
  for _ in $(seq 1 20); do
    [ "$(curl -s -o /dev/null -w '%{http_code}' "$URL/health")" = "200" ] || return 1
  done
}
