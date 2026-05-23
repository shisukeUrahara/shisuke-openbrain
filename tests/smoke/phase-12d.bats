#!/usr/bin/env bats
# Phase 12.d smoke — audio worker on the live local stack.
#
# We do not exercise a real transcription here because the first
# job loads a ~250 MB whisper model and live ingestion needs the
# user's OPENROUTER_API_KEY on the mcp-server. The bats suite
# stays above that line — container up, log lines per flag, two
# queues reachable, mcp-server reachable.
#
# Prereqs:
#   docker compose --profile audio up -d
#
# Run:
#   bats tests/smoke/phase-12d.bats

setup() {
  :
}

@test "worker-audio container is up" {
  run docker compose --profile audio ps worker-audio
  [[ "$output" == *"Up"* ]] || [[ "$output" == *"running"* ]] || [[ "$output" == *"healthy"* ]]
}

@test "worker-audio reports ready to consume when flag is true" {
  flag=$(docker compose --profile audio exec -T worker-audio \
    sh -c 'echo "${MODULE_WORKERS_AUDIO_ENABLED:-false}"' | tr -d '\r\n')
  if [ "$flag" != "true" ]; then
    skip "module is disabled in this container"
  fi
  run docker compose --profile audio logs --tail=30 worker-audio
  [[ "$output" == *"audio worker ready"* ]]
}

@test "worker-audio reports idle when flag is false" {
  flag=$(docker compose --profile audio exec -T worker-audio \
    sh -c 'echo "${MODULE_WORKERS_AUDIO_ENABLED:-false}"' | tr -d '\r\n')
  if [ "$flag" = "true" ]; then
    skip "module is active — see other suite"
  fi
  run docker compose --profile audio logs --tail=20 worker-audio
  [[ "$output" == *"audio worker is idle"* ]]
}

@test "worker-audio reaches the mcp-server" {
  run docker compose --profile audio exec -T worker-audio \
    python -c "import httpx
print(httpx.get('http://mcp-server:8080/health', timeout=5.0).status_code)
"
  [ "$status" -eq 0 ]
  [ "$output" = "200" ]
}

@test "worker-audio reaches redis with both queue keys" {
  run docker compose --profile audio exec -T worker-audio \
    python -c "import asyncio,os
from redis import asyncio as aioredis
async def main():
    r = aioredis.from_url(os.environ['REDIS_URL'], decode_responses=True)
    print(await r.ping())
    print(await r.llen('ingest:voice'))
    print(await r.llen('ingest:youtube'))
    await r.aclose()
asyncio.run(main())
"
  [ "$status" -eq 0 ]
  [[ "$output" == *"True"* ]]
}

@test "ffmpeg + yt-dlp are installed in the container" {
  run docker compose --profile audio exec -T worker-audio \
    sh -c "which ffmpeg && which yt-dlp"
  [ "$status" -eq 0 ]
  [[ "$output" == *"/ffmpeg"* ]]
  [[ "$output" == *"/yt-dlp"* ]]
}
