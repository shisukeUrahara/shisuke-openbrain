#!/usr/bin/env bats
# Phase 1 smoke tests — outside-in checks against a running stack.
#
# Prerequisites:
#   docker compose up -d postgres
#   wait for healthy
#
# Run:
#   bats tests/smoke/phase-01.bats

setup() {
  export DSN="postgresql://${POSTGRES_USER:-postgres}:${POSTGRES_PASSWORD:-devpass}@localhost:${POSTGRES_PORT:-5432}/${POSTGRES_DB:-openbrain}"
}

@test "postgres container is healthy" {
  run docker compose ps --format json postgres
  [[ "$output" == *'"Health":"healthy"'* ]] || [[ "$output" == *'"State":"running"'* ]]
}

@test "psql can connect" {
  run psql "$DSN" -tAc "SELECT 1"
  [ "$status" -eq 0 ]
  [ "$output" = "1" ]
}

@test "vector extension is installed" {
  run psql "$DSN" -tAc "SELECT 1 FROM pg_extension WHERE extname='vector'"
  [ "$status" -eq 0 ]
  [ "$output" = "1" ]
}

@test "pg_trgm extension is installed" {
  run psql "$DSN" -tAc "SELECT 1 FROM pg_extension WHERE extname='pg_trgm'"
  [ "$status" -eq 0 ]
  [ "$output" = "1" ]
}

@test "uuid-ossp extension is installed" {
  run psql "$DSN" -tAc "SELECT 1 FROM pg_extension WHERE extname='uuid-ossp'"
  [ "$status" -eq 0 ]
  [ "$output" = "1" ]
}

@test "thoughts table exists with expected columns" {
  run psql "$DSN" -tAc "SELECT count(*) FROM information_schema.columns WHERE table_name='thoughts'"
  [ "$status" -eq 0 ]
  [ "$output" -ge 7 ]   # id, content, embedding, metadata, created_at, updated_at, content_fingerprint
}

@test "match_thoughts function exists" {
  run psql "$DSN" -tAc "SELECT count(*) FROM pg_proc WHERE proname='match_thoughts'"
  [ "$status" -eq 0 ]
  [ "$output" = "1" ]
}

@test "upsert_thought function exists" {
  run psql "$DSN" -tAc "SELECT count(*) FROM pg_proc WHERE proname='upsert_thought'"
  [ "$status" -eq 0 ]
  [ "$output" = "1" ]
}

@test "upsert_thought dedupes identical content" {
  psql "$DSN" -tAc "DELETE FROM thoughts WHERE content = 'bats smoke duplicate'" > /dev/null
  psql "$DSN" -tAc "SELECT upsert_thought('bats smoke duplicate', '{}'::jsonb)" > /dev/null
  psql "$DSN" -tAc "SELECT upsert_thought('bats smoke duplicate', '{}'::jsonb)" > /dev/null
  run psql "$DSN" -tAc "SELECT count(*) FROM thoughts WHERE content = 'bats smoke duplicate'"
  [ "$status" -eq 0 ]
  [ "$output" = "1" ]
  psql "$DSN" -tAc "DELETE FROM thoughts WHERE content = 'bats smoke duplicate'" > /dev/null
}

@test "HNSW vector index exists on embedding column" {
  run psql "$DSN" -tAc "SELECT count(*) FROM pg_indexes WHERE tablename='thoughts' AND indexname='thoughts_embedding_idx'"
  [ "$status" -eq 0 ]
  [ "$output" = "1" ]
}

@test "GIN metadata index exists" {
  run psql "$DSN" -tAc "SELECT count(*) FROM pg_indexes WHERE tablename='thoughts' AND indexname='thoughts_metadata_idx'"
  [ "$status" -eq 0 ]
  [ "$output" = "1" ]
}

@test "container persistence — restart preserves the volume" {
  # Insert a marker row, restart postgres, confirm it survives.
  marker="bats persistence marker $(date +%s)"
  psql "$DSN" -tAc "INSERT INTO thoughts (content) VALUES ('$marker')" > /dev/null
  docker compose restart postgres > /dev/null
  # Wait for healthy again.
  for _ in {1..30}; do
    if psql "$DSN" -tAc "SELECT 1" > /dev/null 2>&1; then break; fi
    sleep 1
  done
  run psql "$DSN" -tAc "SELECT count(*) FROM thoughts WHERE content = '$marker'"
  [ "$status" -eq 0 ]
  [ "$output" = "1" ]
  psql "$DSN" -tAc "DELETE FROM thoughts WHERE content = '$marker'" > /dev/null
}
