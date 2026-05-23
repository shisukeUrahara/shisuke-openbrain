#!/usr/bin/env bats
# Phase 11 smoke — telegram-bot service (idle-mode contract).
#
# These tests confirm the container starts and stays up WITHOUT a
# Telegram token because the module flag is false. Once the user
# sets MODULE_TELEGRAM_BOT_ENABLED=true and provides the token they
# can extend this suite with the active-mode contract.
#
# Prereqs:
#   docker compose --profile telegram up -d
#
# Run:
#   bats tests/smoke/phase-11.bats

setup() {
  :
}

@test "redis container is healthy" {
  run docker compose ps --format json redis
  [[ "$output" == *'"Health":"healthy"'* ]] || [[ "$output" == *'"State":"running"'* ]]
}

@test "telegram-bot container is running" {
  run docker compose ps --format json telegram-bot
  [[ "$output" == *'"State":"running"'* ]]
}

@test "telegram-bot logs report idle when flag is false" {
  # Only runs when MODULE_TELEGRAM_BOT_ENABLED is not 'true' on the
  # running container. Skip otherwise — active-mode logs are
  # different.
  flag_in_container=$(docker compose exec -T telegram-bot \
    sh -c 'echo "${MODULE_TELEGRAM_BOT_ENABLED:-false}"' | tr -d '\r\n')
  if [ "$flag_in_container" = "true" ]; then
    skip "module is active in this container — see phase-11-active.bats"
  fi
  run docker compose logs --tail=20 telegram-bot
  [[ "$output" == *"service is idle"* ]]
}

@test "redis is reachable from telegram-bot's network" {
  run docker compose exec -T telegram-bot \
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

@test "mcp-server is reachable from telegram-bot's network" {
  run docker compose exec -T telegram-bot \
    python -c "import httpx
print(httpx.get('http://mcp-server:8080/health', timeout=5.0).status_code)
"
  [ "$status" -eq 0 ]
  [ "$output" = "200" ]
}
