#!/usr/bin/env bats
# Phase 5 smoke — the schema-load + schema-check scripts against the
# live LOCAL Postgres. This is the same schema and the same scripts
# that go to production; exercising them locally is the prep that lets
# the actual Coolify load (Phase 5 on the VPS) be copy-paste.
#
# Prereqs:
#   docker compose up -d   (postgres healthy)
#
# Run:
#   set -a; source .env; set +a
#   bats tests/smoke/phase-05.bats

setup() {
  DSN="postgresql://${POSTGRES_USER:-postgres}:${POSTGRES_PASSWORD:-devpass}@localhost:${POSTGRES_PORT:-5432}/${POSTGRES_DB:-openbrain}"
  export DSN
  if ! psql "$DSN" -tAc "select 1" >/dev/null 2>&1; then
    skip "local Postgres not reachable (docker compose up -d)"
  fi
}

@test "load-schema applies core migrations" {
  run env DATABASE_URL="$DSN" bash scripts/load-schema.sh
  [ "$status" -eq 0 ]
  [[ "$output" == *"done."* ]]
}

@test "load-schema is idempotent (second run also clean)" {
  run env DATABASE_URL="$DSN" bash scripts/load-schema.sh
  [ "$status" -eq 0 ]
}

@test "load-schema never prints the DSN password" {
  run env DATABASE_URL="$DSN" bash scripts/load-schema.sh
  [ "$status" -eq 0 ]
  [[ "$output" != *"${POSTGRES_PASSWORD:-devpass}"* ]]
  [[ "$output" == *"***"* ]]
}

@test "check-pgvector confirms extensions, tables, functions" {
  run env DATABASE_URL="$DSN" bash scripts/check-pgvector.sh
  [ "$status" -eq 0 ]
  [[ "$output" == *"schema OK"* ]]
}

@test "documents module loads via --with-module" {
  run env DATABASE_URL="$DSN" bash scripts/load-schema.sh --with-module documents
  [ "$status" -eq 0 ]
  [[ "$output" == *"module: documents"* ]]
}

@test "thoughts table exists and is queryable" {
  run psql "$DSN" -tAc "select count(*) >= 0 from thoughts"
  [ "$status" -eq 0 ]
  [ "$output" = "t" ]
}
