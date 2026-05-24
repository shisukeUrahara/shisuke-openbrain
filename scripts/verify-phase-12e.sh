#!/usr/bin/env bash
# Phase 12.e acceptance gate — image worker.
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

echo "── phase 12.e: prerequisites ──"
for prev in 00 01 02 10; do
  if bash "scripts/verify-phase-$prev.sh" >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m phase-%s gate passes\n" "$prev"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m phase-%s gate FAILS\n" "$prev"; fail=$((fail+1))
  fi
done

echo "── phase 12.e: scaffold ──"
check "test -s services/workers/image/pyproject.toml"            "pyproject.toml present"
check "test -s services/workers/image/Dockerfile"                 "Dockerfile present"
check "test -s services/workers/image/README.md"                  "README.md present"
for m in __init__.py config.py chunker.py fetcher.py analyzer.py mcp_client.py queue.py worker.py; do
  check "test -s services/workers/image/src/worker_image/$m"      "src/worker_image/$m present"
done

echo "── phase 12.e: docker-compose ──"
check "grep -q '^\\s*worker-image:' docker-compose.yml"             "worker-image service declared"
check "docker compose --profile image config | grep -A20 '^\\s*worker-image:' | grep -q 'profiles:'" \
       "worker-image uses image profile"
check "grep -q 'MODULE_WORKERS_IMAGE_ENABLED' docker-compose.yml"   "module flag wired"
check "grep -q 'ingest:image' docker-compose.yml"                   "default queue ingest:image wired"
check "grep -q 'WORKER_VISION_MODEL' docker-compose.yml"            "vision model env wired"
check "docker compose --profile image config --quiet"               "compose lints clean with image profile"

echo "── phase 12.e: unit tests ──"
if command -v pytest >/dev/null 2>&1; then
  if pytest services/workers/image/tests/unit -q --tb=no >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m worker-image pytest suite passes\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m worker-image pytest suite FAILED\n"
    fail=$((fail+1))
  fi
else
  skip_with "worker-image pytest suite" "pytest not installed"
fi

echo "── phase 12.e: live smoke ──"
if docker compose --profile image ps worker-image 2>/dev/null | grep -qE 'Up|running|healthy'; then
  if bats tests/smoke/phase-12e.bats >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m phase-12e bats smoke passes\n"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m phase-12e bats smoke FAILED\n"
    fail=$((fail+1))
  fi
else
  skip_with "phase-12e bats smoke" "worker-image container is not running (start with docker compose --profile image up -d)"
fi

echo
total=$((pass + fail))
if [ "$fail" -eq 0 ]; then
  printf "\033[32mphase 12.e: OK (%d/%d, %d skipped)\033[0m\n" "$pass" "$total" "$skip"
  exit 0
else
  printf "\033[31mphase 12.e: FAIL (%d/%d passed, %d failed, %d skipped)\033[0m\n" "$pass" "$total" "$fail" "$skip"
  exit 1
fi
