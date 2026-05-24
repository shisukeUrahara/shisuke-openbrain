#!/usr/bin/env bats
# Phase 14 smoke — n8n scheduler on the live local stack.
#
# Prereqs:
#   docker compose --profile n8n up -d n8n
#
# Run:
#   bats tests/smoke/phase-14.bats

setup() {
  export DSN="postgresql://${POSTGRES_USER:-postgres}:${POSTGRES_PASSWORD:-devpass}@localhost:${POSTGRES_PORT:-5432}/${POSTGRES_DB:-openbrain}"
  export N8N_URL="http://localhost:${N8N_PORT:-5678}"
}

@test "n8n container is up" {
  run docker compose --profile n8n ps n8n
  [[ "$output" == *"Up"* ]] || [[ "$output" == *"running"* ]] || [[ "$output" == *"healthy"* ]]
}

@test "n8n healthz endpoint returns 200" {
  run curl -s -o /dev/null -w '%{http_code}' "$N8N_URL/healthz"
  [ "$status" -eq 0 ]
  [ "$output" = "200" ]
}

@test "n8n editor is served" {
  run curl -s -o /dev/null -w '%{http_code}' "$N8N_URL/"
  [ "$status" -eq 0 ]
  [ "$output" = "200" ]
}

@test "n8n created its dedicated schema in the shared Postgres" {
  run psql "$DSN" -tAc "SELECT count(*) FROM information_schema.schemata WHERE schema_name='n8n'"
  [ "$status" -eq 0 ]
  [ "$output" = "1" ]
}

@test "n8n schema does not pollute the brain tables" {
  # thoughts/documents/chunks must still live in public, untouched.
  run psql "$DSN" -tAc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('thoughts','documents','chunks')"
  [ "$status" -eq 0 ]
  [ "$output" = "3" ]
}

@test "workflow templates are mounted in the container" {
  run docker compose --profile n8n exec -T n8n sh -c "ls /workflows/*.json | wc -l"
  [ "$status" -eq 0 ]
  [ "$output" -ge 2 ]
}

@test "daily-digest workflow JSON is valid and importable shape" {
  # Validate via jq on the host — the file is in the repo, no need to
  # shell into the container. Asserts the three keys n8n's importer
  # requires (name, nodes, connections) and a non-trivial node count.
  run jq -e '(.name|length>0) and (.nodes|length>=4) and (.connections|length>0)' \
    services/n8n/workflows/daily-digest.json
  [ "$status" -eq 0 ]
}

@test "weekly-review workflow JSON is valid and importable shape" {
  run jq -e '(.name|length>0) and (.nodes|length>=4) and (.connections|length>0)' \
    services/n8n/workflows/weekly-review.json
  [ "$status" -eq 0 ]
}
