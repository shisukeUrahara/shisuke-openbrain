#!/usr/bin/env bats
# Phase 15 outside-in smoke — graphify export module on a live stack.
#
# Unlike the capture paths, export_project_corpus does NOT touch the
# embedding provider — it only reads content columns and writes
# markdown. That lets this suite do a full round-trip without a real
# OPENROUTER_API_KEY: seed two rows straight into Postgres, call the
# tool over MCP, then assert the files landed in the mounted volume.
#
# Prereqs:
#   MODULE_DOCUMENTS_ENABLED=true and MODULE_GRAPHIFY_ENABLED=true in .env
#   docker compose up -d --build
#   set -a; source .env; set +a
#
# Run:
#   bats tests/smoke/phase-15.bats

setup() {
  : "${BRAIN_KEY:?BRAIN_KEY must be exported}"
  URL="http://localhost:8080"
  PROJECT="smoke15-bats"
  PGU="${POSTGRES_USER:-postgres}"
  PGD="${POSTGRES_DB:-openbrain}"
}

mcp() {
  # $1 = JSON-RPC body, $2 = jq filter. Strips an optional SSE `data: `
  # prefix so this works whether the server replies with plain JSON or
  # text/event-stream. Called directly via `run` (not through a
  # `bash -c` subshell) so it inherits $URL/$BRAIN_KEY from setup().
  curl -s -X POST "$URL/mcp" \
    -H "x-brain-key: $BRAIN_KEY" \
    -H 'Content-Type: application/json' \
    -H 'Accept: application/json, text/event-stream' \
    -d "$1" | sed 's/^data: //' | jq -r "$2"
}

psql_run() {
  docker compose exec -T postgres psql -U "$PGU" -d "$PGD" -v ON_ERROR_STOP=1 "$@"
}

@test "/health reports graphify module enabled" {
  run bash -c "curl -s '$URL/health' | jq -r '.modules.graphify'"
  [ "$status" -eq 0 ]
  [ "$output" = "true" ]
}

@test "tools/list returns 8 tools (4 core + 3 documents + 1 graphify)" {
  run mcp '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' '.result.tools | length'
  [ "$status" -eq 0 ]
  [ "$output" = "8" ]
}

@test "tools/list includes export_project_corpus" {
  run mcp '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' '.result.tools[].name'
  [ "$status" -eq 0 ]
  [[ "$output" == *"export_project_corpus"* ]]
}

@test "export_project_corpus rejects an empty project (validation path)" {
  run mcp '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"export_project_corpus","arguments":{"project":" "}}}' '.result.isError'
  [ "$status" -eq 0 ]
  [ "$output" = "true" ]
}

@test "export round-trip writes markdown files to the exports volume" {
  # Seed one document + one thought tagged with the project. These rows
  # carry no embedding, which is fine — export only reads content.
  psql_run <<SQL
insert into documents (title, kind, source, content_md, project, sha256)
values ('Bats Doc 15','article','http://x','# Hello

body','$PROJECT','sha-bats-15')
on conflict (sha256) where sha256 is not null do nothing;
insert into thoughts (content, metadata)
values ('Graphify bats export thought', '{"project":"$PROJECT","type":"note"}'::jsonb);
SQL

  # Call the tool.
  run mcp "{\"jsonrpc\":\"2.0\",\"id\":4,\"method\":\"tools/call\",\"params\":{\"name\":\"export_project_corpus\",\"arguments\":{\"project\":\"$PROJECT\"}}}" '.result.content[0].text | fromjson | "\(.documents) \(.thoughts)"'
  [ "$status" -eq 0 ]
  [ "$output" = "1 1" ]

  # The files must exist inside the container's mounted /exports volume.
  run docker compose exec -T mcp-server sh -c "ls /exports/$PROJECT/_thoughts.md /exports/$PROJECT/article__Bats_Doc_15.md"
  [ "$status" -eq 0 ]

  # The thoughts file must contain the rendered line with its type tag.
  run docker compose exec -T mcp-server sh -c "cat /exports/$PROJECT/_thoughts.md"
  [ "$status" -eq 0 ]
  [[ "$output" == *"[note] Graphify bats export thought"* ]]
}

teardown() {
  # Best-effort cleanup so reruns stay deterministic and the brain
  # is not polluted with smoke rows. Qualified deletes only.
  if [ -n "${PROJECT:-}" ]; then
    psql_run -c "delete from documents where project = '$PROJECT'" >/dev/null 2>&1 || true
    psql_run -c "delete from thoughts where metadata ->> 'project' = '$PROJECT'" >/dev/null 2>&1 || true
    docker compose exec -T mcp-server rm -rf "/exports/$PROJECT" >/dev/null 2>&1 || true
  fi
}
