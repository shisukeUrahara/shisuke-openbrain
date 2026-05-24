#!/usr/bin/env bats
# Phase 7 smoke — the client-endpoint validator against the live LOCAL
# server. Every client (Claude Code, Desktop, ChatGPT, Cursor) hits the
# same endpoint with the same key, so validating it locally proves the
# logic clients depend on. The real cross-client test happens against
# the deployment.
#
# Prereqs:
#   docker compose up -d
#   set -a; source .env; set +a
#
# Run:
#   bats tests/smoke/phase-07.bats

setup() {
  : "${BRAIN_KEY:?BRAIN_KEY must be exported}"
  URL="http://localhost:8080/mcp"
  if [ "$(curl -s -o /dev/null -w '%{http_code}' http://localhost:8080/health)" != "200" ]; then
    skip "mcp-server not reachable (docker compose up -d)"
  fi
}

@test "check-client-endpoint accepts a good URL + key" {
  run bash scripts/check-client-endpoint.sh "$URL" "$BRAIN_KEY"
  [ "$status" -eq 0 ]
  [[ "$output" == *"endpoint OK"* ]]
}

@test "check-client-endpoint rejects a wrong key (non-zero exit)" {
  run bash scripts/check-client-endpoint.sh "$URL" "definitely-wrong"
  [ "$status" -ne 0 ]
}

@test "check-client-endpoint warns on a trailing slash" {
  run bash scripts/check-client-endpoint.sh "$URL/" "$BRAIN_KEY"
  [[ "$output" == *"trailing slash"* ]]
}

@test "endpoint confirms wrong key -> 401" {
  run bash scripts/check-client-endpoint.sh "$URL" "$BRAIN_KEY"
  [ "$status" -eq 0 ]
  [[ "$output" == *"wrong key rejected with 401"* ]]
}
