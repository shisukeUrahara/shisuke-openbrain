#!/usr/bin/env bats
# Phase 12.c smoke — pdf worker on the live local stack.
#
# Live end-to-end ingestion requires OPENROUTER_API_KEY on the
# mcp-server. These smoke tests stay above that line: container up,
# log lines per flag state, queue drains, mcp-server reachable.
#
# Prereqs:
#   docker compose --profile pdf up -d
#
# Run:
#   bats tests/smoke/phase-12c.bats

setup() {
  :
}

@test "worker-pdf container is up" {
  run docker compose --profile pdf ps worker-pdf
  [[ "$output" == *"Up"* ]] || [[ "$output" == *"running"* ]] || [[ "$output" == *"healthy"* ]]
}

@test "worker-pdf reports ready to consume when flag is true" {
  flag=$(docker compose --profile pdf exec -T worker-pdf \
    sh -c 'echo "${MODULE_WORKERS_PDF_ENABLED:-false}"' | tr -d '\r\n')
  if [ "$flag" != "true" ]; then
    skip "module is disabled in this container"
  fi
  run docker compose --profile pdf logs --tail=20 worker-pdf
  [[ "$output" == *"pdf worker ready"* ]]
}

@test "worker-pdf reports idle when flag is false" {
  flag=$(docker compose --profile pdf exec -T worker-pdf \
    sh -c 'echo "${MODULE_WORKERS_PDF_ENABLED:-false}"' | tr -d '\r\n')
  if [ "$flag" = "true" ]; then
    skip "module is active — see other suite"
  fi
  run docker compose --profile pdf logs --tail=20 worker-pdf
  [[ "$output" == *"pdf worker is idle"* ]]
}

@test "worker-pdf reaches the mcp-server" {
  run docker compose --profile pdf exec -T worker-pdf \
    python -c "import httpx
print(httpx.get('http://mcp-server:8080/health', timeout=5.0).status_code)
"
  [ "$status" -eq 0 ]
  [ "$output" = "200" ]
}

@test "worker-pdf reaches redis" {
  run docker compose --profile pdf exec -T worker-pdf \
    python -c "import asyncio,os
from redis import asyncio as aioredis
async def main():
    r = aioredis.from_url(os.environ['REDIS_URL'], decode_responses=True)
    print(await r.ping())
    await r.aclose()
asyncio.run(main())
"
  [ "$status" -eq 0 ]
  [[ "$output" == *"True"* ]]
}
