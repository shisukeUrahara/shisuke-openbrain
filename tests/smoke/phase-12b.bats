#!/usr/bin/env bats
# Phase 12.b smoke — article worker on the live local stack.
#
# Prereqs:
#   docker compose --profile article up -d
#   MODULE_WORKERS_ARTICLE_ENABLED=true in .env
#
# Run:
#   bats tests/smoke/phase-12b.bats
#
# We do NOT exercise the full fetch -> embed -> insert pipeline here
# because that requires the user's OPENROUTER_API_KEY on the
# mcp-server container. Live ingestion tests live in the operator
# runbook (docs/phase-12b-go-live.md) and run after the user wires
# their key in.

setup() {
  :
}

@test "worker-article container is up" {
  run docker compose --profile article ps worker-article
  [[ "$output" == *"Up"* ]] || [[ "$output" == *"running"* ]] || [[ "$output" == *"healthy"* ]]
}

@test "worker-article reports ready to consume when flag is true" {
  flag_in_container=$(docker compose --profile article exec -T worker-article \
    sh -c 'echo "${MODULE_WORKERS_ARTICLE_ENABLED:-false}"' | tr -d '\r\n')
  if [ "$flag_in_container" != "true" ]; then
    skip "module is disabled in this container"
  fi
  run docker compose --profile article logs --tail=20 worker-article
  [[ "$output" == *"article worker ready"* ]]
}

@test "worker-article reports idle when flag is false" {
  flag_in_container=$(docker compose --profile article exec -T worker-article \
    sh -c 'echo "${MODULE_WORKERS_ARTICLE_ENABLED:-false}"' | tr -d '\r\n')
  if [ "$flag_in_container" = "true" ]; then
    skip "module is active in this container — see other suite"
  fi
  run docker compose --profile article logs --tail=20 worker-article
  [[ "$output" == *"worker is idle"* ]]
}

@test "redis queue ingest:article is empty after consuming pushed jobs" {
  # If the worker is running and consuming, anything we push should
  # disappear from the list within a few seconds. Even on a
  # missing-key error the worker still acks the job.
  docker compose --profile article exec -T redis redis-cli LPUSH ingest:article \
    '{"url":"https://example.com/"}' >/dev/null
  sleep 3
  run docker compose --profile article exec -T redis redis-cli LLEN ingest:article
  # Trim whitespace and carriage returns from redis-cli output.
  len="${output//[[:space:]]/}"
  [ "$len" = "0" ]
}

@test "worker-article reaches the mcp-server" {
  run docker compose --profile article exec -T worker-article \
    python -c "import httpx
print(httpx.get('http://mcp-server:8080/health', timeout=5.0).status_code)
"
  [ "$status" -eq 0 ]
  [ "$output" = "200" ]
}
