#!/usr/bin/env bats
# Phase 2 outside-in smoke tests.
#
# Prerequisites: full local stack up (`docker compose up -d`).
#                BRAIN_KEY exported in the environment or sourced from .env.
#
# Run:
#   docker compose up -d
#   set -a; source .env; set +a
#   bats tests/smoke/phase-02.bats
#
# These tests intentionally do NOT exercise the capture tool because
# capture requires a real OPENROUTER_API_KEY. Capture and search are
# covered end-to-end in the integration suite (mocked embedding) and
# will be tested live once the user wires their OpenRouter key.

setup() {
  : "${BRAIN_KEY:?BRAIN_KEY must be exported}"
  URL="http://localhost:8080"
}

@test "mcp-server container is healthy" {
  run docker compose ps --format json mcp-server
  [[ "$output" == *'"Health":"healthy"'* ]] || [[ "$output" == *'"State":"running"'* ]]
}

@test "GET /health returns ok without key" {
  run curl -s "$URL/health"
  [ "$status" -eq 0 ]
  [[ "$output" == *'"ok":true'* ]]
}

@test "GET /health surfaces every module flag" {
  run bash -c "curl -s '$URL/health' | jq -r '.modules | keys | length'"
  [ "$status" -eq 0 ]
  [ "$output" = "9" ]   # documents, telegram_bot, 4 workers, obsidian, n8n, graphify
}

@test "POST /mcp without key returns 401" {
  run curl -s -o /dev/null -w '%{http_code}' \
    -X POST "$URL/mcp" -H 'Content-Type: application/json' -H 'Accept: application/json' \
    -d '{}'
  [ "$status" -eq 0 ]
  [ "$output" = "401" ]
}

@test "POST /mcp with wrong key returns 401" {
  run curl -s -o /dev/null -w '%{http_code}' \
    -X POST "$URL/mcp" \
    -H "x-brain-key: definitely-not-the-key" \
    -H 'Content-Type: application/json' -H 'Accept: application/json' \
    -d '{}'
  [ "$status" -eq 0 ]
  [ "$output" = "401" ]
}

@test "POST /mcp with header key — tools/list returns 4 core tools" {
  run bash -c "curl -s -X POST '$URL/mcp' \
    -H 'x-brain-key: $BRAIN_KEY' \
    -H 'Content-Type: application/json' -H 'Accept: application/json' \
    -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\",\"params\":{}}' \
    | jq -r '.result.tools | length'"
  [ "$status" -eq 0 ]
  [ "$output" = "4" ]
}

@test "POST /mcp with query key — tools/list returns 4 core tools" {
  run bash -c "curl -s -X POST '$URL/mcp?key=$BRAIN_KEY' \
    -H 'Content-Type: application/json' -H 'Accept: application/json' \
    -d '{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/list\",\"params\":{}}' \
    | jq -r '.result.tools | length'"
  [ "$status" -eq 0 ]
  [ "$output" = "4" ]
}

@test "tools/list includes the expected tool names" {
  run bash -c "curl -s -X POST '$URL/mcp' \
    -H 'x-brain-key: $BRAIN_KEY' \
    -H 'Content-Type: application/json' -H 'Accept: application/json' \
    -d '{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"tools/list\",\"params\":{}}' \
    | jq -r '.result.tools[].name' | sort | tr '\n' ' '"
  [ "$status" -eq 0 ]
  [ "$output" = "browse capture search stats " ]
}

@test "browse tool round-trip — returns a list (possibly empty)" {
  run bash -c "curl -s -X POST '$URL/mcp' \
    -H 'x-brain-key: $BRAIN_KEY' \
    -H 'Content-Type: application/json' -H 'Accept: application/json' \
    -d '{\"jsonrpc\":\"2.0\",\"id\":4,\"method\":\"tools/call\",\"params\":{\"name\":\"browse\",\"arguments\":{\"limit\":5}}}' \
    | jq -r '.result.structuredContent.result | type'"
  [ "$status" -eq 0 ]
  [ "$output" = "array" ]
}

@test "stats tool round-trip — returns aggregate object with total_thoughts" {
  # Dict-returning tools surface their payload at structuredContent (no .result
  # wrapper). List-returning tools surface theirs at structuredContent.result.
  run bash -c "curl -s -X POST '$URL/mcp' \
    -H 'x-brain-key: $BRAIN_KEY' \
    -H 'Content-Type: application/json' -H 'Accept: application/json' \
    -d '{\"jsonrpc\":\"2.0\",\"id\":5,\"method\":\"tools/call\",\"params\":{\"name\":\"stats\",\"arguments\":{}}}' \
    | jq -r '.result.structuredContent.total_thoughts | type'"
  [ "$status" -eq 0 ]
  [ "$output" = "number" ]
}
