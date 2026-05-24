#!/usr/bin/env bats
# Phase 12.e smoke — image worker on the live local stack.

setup() { :; }

@test "worker-image container is up" {
  run docker compose --profile image ps worker-image
  [[ "$output" == *"Up"* ]] || [[ "$output" == *"running"* ]] || [[ "$output" == *"healthy"* ]]
}

@test "worker-image reports ready when flag is true" {
  flag=$(docker compose --profile image exec -T worker-image \
    sh -c 'echo "${MODULE_WORKERS_IMAGE_ENABLED:-false}"' | tr -d '\r\n')
  if [ "$flag" != "true" ]; then
    skip "module is disabled in this container"
  fi
  run docker compose --profile image logs --tail=20 worker-image
  [[ "$output" == *"image worker ready"* ]]
}

@test "worker-image reports idle when flag is false" {
  flag=$(docker compose --profile image exec -T worker-image \
    sh -c 'echo "${MODULE_WORKERS_IMAGE_ENABLED:-false}"' | tr -d '\r\n')
  if [ "$flag" = "true" ]; then
    skip "module is active — see other suite"
  fi
  run docker compose --profile image logs --tail=20 worker-image
  [[ "$output" == *"image worker is idle"* ]]
}

@test "worker-image reaches the mcp-server" {
  run docker compose --profile image exec -T worker-image \
    python -c "import httpx
print(httpx.get('http://mcp-server:8080/health', timeout=5.0).status_code)
"
  [ "$status" -eq 0 ]
  [ "$output" = "200" ]
}

@test "worker-image reaches redis" {
  run docker compose --profile image exec -T worker-image \
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
