#!/usr/bin/env bats
# Phase 8 smoke — the backup + restore-drill scripts against the live
# LOCAL DB. Same scripts that run against production; proving the loop
# locally is what makes "untested backup = no backup" not apply.
#
# Prereqs:
#   docker compose up -d
#   set -a; source .env; set +a
#
# Run:
#   bats tests/smoke/phase-08.bats

setup() {
  DSN="postgresql://${POSTGRES_USER:-postgres}:${POSTGRES_PASSWORD:-devpass}@localhost:${POSTGRES_PORT:-5432}/${POSTGRES_DB:-openbrain}"
  export DSN
  command -v docker >/dev/null 2>&1 || skip "docker not available"
  psql "$DSN" -tAc "select 1" >/dev/null 2>&1 || skip "local Postgres not reachable"
  TMP="$(mktemp -d)"
}

teardown() {
  [ -n "${TMP:-}" ] && rm -rf "$TMP"
}

@test "backup-db produces a gzipped dump and masks the password" {
  run env DATABASE_URL="$DSN" bash scripts/backup-db.sh --out "$TMP"
  [ "$status" -eq 0 ]
  [[ "$output" != *"${POSTGRES_PASSWORD:-devpass}"* ]]
  [[ "$output" == *"***"* ]]
  run bash -c "ls '$TMP'/*.sql.gz"
  [ "$status" -eq 0 ]
}

@test "restore-test restores the dump into a throwaway PG and asserts thoughts" {
  env DATABASE_URL="$DSN" bash scripts/backup-db.sh --out "$TMP" >/dev/null
  bk="$(ls -t "$TMP"/*.sql.gz | head -1)"
  run bash scripts/restore-test.sh "$bk"
  [ "$status" -eq 0 ]
  [[ "$output" == *"restored OK"* ]]
  [[ "$output" == *"thoughts table present"* ]]
}

@test "restore-test rejects an unsupported format" {
  echo "junk" > "$TMP/bad.txt"
  run bash scripts/restore-test.sh "$TMP/bad.txt"
  [ "$status" -ne 0 ]
}
