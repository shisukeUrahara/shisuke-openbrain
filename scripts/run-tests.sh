#!/usr/bin/env bash
# Master test runner. Dispatches to pytest or bats based on mode.
# Usage: scripts/run-tests.sh {unit|integration|e2e|smoke|phase:NN|all}
set -euo pipefail

mode="${1:-all}"
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

run_unit() {
  if compgen -G "services/*/tests/unit/test_*.py" >/dev/null; then
    pytest services/*/tests/unit -v
  else
    echo "[run-tests] no unit tests yet — skipping"
  fi
}

run_integration() {
  if compgen -G "services/*/tests/integration/test_*.py" >/dev/null; then
    pytest services/*/tests/integration -v
  else
    echo "[run-tests] no integration tests yet — skipping"
  fi
}

run_e2e() {
  if compgen -G "tests/e2e/test_*.py" >/dev/null; then
    pytest tests/e2e -v
  else
    echo "[run-tests] no e2e tests yet — skipping"
  fi
}

run_smoke() {
  if compgen -G "tests/smoke/*.bats" >/dev/null; then
    bats tests/smoke
  else
    echo "[run-tests] no smoke tests yet — skipping"
  fi
}

case "$mode" in
  unit)        run_unit ;;
  integration) run_integration ;;
  e2e)         run_e2e ;;
  smoke)       run_smoke ;;
  phase:*)     bash "scripts/verify-phase-${mode#phase:}.sh" ;;
  all)         run_unit && run_integration && run_e2e && run_smoke ;;
  *)           echo "usage: $0 {unit|integration|e2e|smoke|phase:NN|all}"; exit 2 ;;
esac
