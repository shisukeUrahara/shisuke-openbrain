#!/usr/bin/env bash
# Phase 12.d acceptance gate — audio + youtube worker.
set -uo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

fail=0
pass=0
skip=0
check() {
  if eval "$1" >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m %s\n" "$2"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m %s\n" "$2"; fail=$((fail+1))
  fi
}
skip_with() {
  printf "  \033[33m·\033[0m %s (skipped: %s)\n" "$1" "$2"; skip=$((skip+1))
}

echo "── phase 12.d: prerequisites ──"
for prev in 00 01 02 10; do
  if bash "scripts/verify-phase-$prev.sh" >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m phase-%s gate passes\n" "$prev"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m phase-%s gate FAILS\n" "$prev"; fail=$((fail+1))
  fi
done

echo "── phase 12.d: scaffold ──"
check "test -s services/workers/audio/pyproject.toml"            "pyproject.toml present"
check "test -s services/workers/audio/Dockerfile"                 "Dockerfile present"
check "test -s services/workers/audio/README.md"                  "README.md present"
for m in __init__.py config.py chunker.py fetcher.py transcriber.py mcp_client.py queue.py worker.py; do
  check "test -s services/workers/audio/src/worker_audio/$m"      "src/worker_audio/$m present"
done

echo "── phase 12.d: docker-compose ──"
check "grep -q '^\\s*worker-audio:' docker-compose.yml"             "worker-audio service declared"
check "docker compose --profile audio config | grep -A20 '^\\s*worker-audio:' | grep -q 'profiles:'" \
       "worker-audio uses audio profile"
check "grep -q 'MODULE_WORKERS_AUDIO_ENABLED' docker-compose.yml"   "module flag wired"
check "grep -q 'ingest:voice' docker-compose.yml"                   "voice queue wired"
check "grep -q 'ingest:youtube' docker-compose.yml"                 "youtube queue wired"
check "grep -q 'WORKER_WHISPER_MODEL' docker-compose.yml"           "whisper model env wired"
check "grep -q 'whisper_models' docker-compose.yml"                 "whisper model cache volume declared"
check "docker compose --profile audio config --quiet"               "compose lints clean with audio profile"

echo "── phase 12.d: unit tests ──"
if command -v pytest >/dev/null 2>&1; then
  if pytest services/workers/audio/tests/unit -q --tb=no >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m worker-audio pytest suite passes\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m worker-audio pytest suite FAILED\n"
    fail=$((fail+1))
  fi
else
  skip_with "worker-audio pytest suite" "pytest not installed"
fi

echo "── phase 12.d: live smoke ──"
if docker compose --profile audio ps worker-audio 2>/dev/null | grep -qE 'Up|running|healthy'; then
  if bats tests/smoke/phase-12d.bats >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m phase-12d bats smoke passes\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m phase-12d bats smoke FAILED\n"
    fail=$((fail+1))
  fi
else
  skip_with "phase-12d bats smoke" "worker-audio container is not running (start with docker compose --profile audio up -d)"
fi

echo
total=$((pass + fail))
if [ "$fail" -eq 0 ]; then
  printf "\033[32mphase 12.d: OK (%d/%d, %d skipped)\033[0m\n" "$pass" "$total" "$skip"
  exit 0
else
  printf "\033[31mphase 12.d: FAIL (%d/%d passed, %d failed, %d skipped)\033[0m\n" "$pass" "$total" "$fail" "$skip"
  exit 1
fi
