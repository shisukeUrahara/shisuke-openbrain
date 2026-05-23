#!/usr/bin/env bats
# Phase 10 outside-in smoke — documents module on a live local stack.
#
# Run only when the documents module flag is true (this suite is
# specifically the flag-on contract). Capture and chunk paths need a
# real or stubbed OPENROUTER_API_KEY for embeddings; the assertions
# below stay above that line (only tools/list + /health surface).
#
# Prereqs:
#   docker compose up -d
#   MODULE_DOCUMENTS_ENABLED=true in .env, then `docker compose up -d --build`
#   BRAIN_KEY exported (or sourced from .env)
#
# Run:
#   set -a; source .env; set +a
#   bats tests/smoke/phase-10.bats

setup() {
  : "${BRAIN_KEY:?BRAIN_KEY must be exported}"
  URL="http://localhost:8080"
}

@test "/health reports documents module enabled" {
  run bash -c "curl -s '$URL/health' | jq -r '.modules.documents'"
  [ "$status" -eq 0 ]
  [ "$output" = "true" ]
}

@test "tools/list returns 7 tools (4 core + 3 documents)" {
  run bash -c "curl -s -X POST '$URL/mcp' \
    -H 'x-brain-key: $BRAIN_KEY' \
    -H 'Content-Type: application/json' -H 'Accept: application/json' \
    -d '{\"jsonrpc\":\"2.0\",\"id\":1,\"method\":\"tools/list\",\"params\":{}}' \
    | jq -r '.result.tools | length'"
  [ "$status" -eq 0 ]
  [ "$output" = "7" ]
}

@test "tools/list includes capture_document, add_chunks, search_chunks" {
  run bash -c "curl -s -X POST '$URL/mcp' \
    -H 'x-brain-key: $BRAIN_KEY' \
    -H 'Content-Type: application/json' -H 'Accept: application/json' \
    -d '{\"jsonrpc\":\"2.0\",\"id\":2,\"method\":\"tools/list\",\"params\":{}}' \
    | jq -r '.result.tools[].name' | sort | tr '\n' ' '"
  [ "$status" -eq 0 ]
  [ "$output" = "add_chunks browse capture capture_document search search_chunks stats " ]
}

@test "capture_document tool is callable (validation path)" {
  # Calling with an empty title should produce a JSON-RPC error with
  # status 200 (errors are in the payload, not the HTTP layer for
  # FastMCP) — proves the tool itself is wired through.
  run bash -c "curl -s -X POST '$URL/mcp' \
    -H 'x-brain-key: $BRAIN_KEY' \
    -H 'Content-Type: application/json' -H 'Accept: application/json' \
    -d '{\"jsonrpc\":\"2.0\",\"id\":3,\"method\":\"tools/call\",\"params\":{\"name\":\"capture_document\",\"arguments\":{\"title\":\" \",\"kind\":\"article\"}}}' \
    | jq -r '.result.isError'"
  [ "$status" -eq 0 ]
  [ "$output" = "true" ]
}

@test "search_chunks tool returns empty list against empty DB" {
  # Empty DB + any valid query: result.structuredContent.result == [].
  run bash -c "curl -s -X POST '$URL/mcp' \
    -H 'x-brain-key: $BRAIN_KEY' \
    -H 'Content-Type: application/json' -H 'Accept: application/json' \
    -d '{\"jsonrpc\":\"2.0\",\"id\":4,\"method\":\"tools/call\",\"params\":{\"name\":\"search_chunks\",\"arguments\":{\"query\":\"anything\",\"match_count\":3}}}' \
    | jq -r '.result.structuredContent.result | length'"
  [ "$status" -eq 0 ]
  # An empty DB returns 0 hits; a non-stubbed openrouter call may error,
  # which surfaces as a tools/call error instead. Accept either: empty
  # result OR an isError flag on the JSON-RPC payload.
  [[ "$output" == "0" || "$output" == "null" ]]
}
