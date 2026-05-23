#!/usr/bin/env bash
# Phase 4 acceptance gate.
#
# Phase 4 is partially repo-side (the harden script and smoke tests)
# and partially environment-side (a real VPS the user has to
# provision and DNS they have to point). This script verifies the
# repo-side artifacts unconditionally, and runs the bats smoke
# against the live VPS when VPS_HOST + VPS_IP are exported.
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

echo "── phase 4: prerequisites ──"
for prev in 00 01 02; do
  if bash "scripts/verify-phase-$prev.sh" >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m phase-%s gate passes\n" "$prev"; pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m phase-%s gate FAILS\n" "$prev"; fail=$((fail+1))
  fi
done

echo "── phase 4: harden script ──"
check "test -x scripts/vps-harden.sh"                                  "scripts/vps-harden.sh is executable"
check "head -1 scripts/vps-harden.sh | grep -q '^#!/usr/bin/env bash'" "bash shebang present"
check "grep -q 'set -euo pipefail' scripts/vps-harden.sh"              "strict bash mode enabled"
check "grep -qE '^require_root\\(\\)'  scripts/vps-harden.sh"          "require_root function defined"
check "grep -qE '^ensure_user\\(\\)'   scripts/vps-harden.sh"          "ensure_user function defined"
check "grep -qE '^configure_ufw\\(\\)' scripts/vps-harden.sh"          "configure_ufw function defined"
check "grep -qE '^harden_ssh\\(\\)'    scripts/vps-harden.sh"          "harden_ssh function defined"
check "grep -qE '^enable_fail2ban\\(\\)' scripts/vps-harden.sh"        "enable_fail2ban function defined"
check "grep -q 'ufw allow 22/tcp'  scripts/vps-harden.sh"              "opens port 22"
check "grep -q 'ufw allow 80/tcp'  scripts/vps-harden.sh"              "opens port 80"
check "grep -q 'ufw allow 443/tcp' scripts/vps-harden.sh"              "opens port 443"
check "grep -q 'ufw allow 8000/tcp' scripts/vps-harden.sh"             "opens port 8000 (Coolify)"
check "grep -q 'PermitRootLogin no'  scripts/vps-harden.sh"            "disables root SSH"
check "grep -q 'PasswordAuthentication no' scripts/vps-harden.sh"      "disables password auth"

echo "── phase 4: smoke test artifact ──"
check "test -s tests/smoke/phase-04.bats"                              "phase-04.bats present"
check "grep -q 'VPS_HOST' tests/smoke/phase-04.bats"                   "phase-04.bats reads VPS_HOST"
check "grep -q 'VPS_IP'   tests/smoke/phase-04.bats"                   "phase-04.bats reads VPS_IP"

echo "── phase 4: live VPS checks (optional) ──"
if [ -n "${VPS_HOST:-}" ] && [ -n "${VPS_IP:-}" ]; then
  : "${VPS_USER:=shisuke}"
  if VPS_HOST="$VPS_HOST" VPS_IP="$VPS_IP" VPS_USER="$VPS_USER" \
       bats tests/smoke/phase-04.bats >/dev/null 2>&1; then
    printf "  \033[32m✓\033[0m phase-04 bats smoke passes against VPS_HOST=%s\n" "$VPS_HOST"
    pass=$((pass+1))
  else
    printf "  \033[31m✗\033[0m phase-04 bats smoke FAILED — run with verbose flag to diagnose\n"
    fail=$((fail+1))
  fi
else
  skip_with "live VPS smoke" "VPS_HOST and VPS_IP not exported"
fi

echo
total=$((pass + fail))
if [ "$fail" -eq 0 ]; then
  printf "\033[32mphase 4: OK (%d/%d, %d skipped)\033[0m\n" "$pass" "$total" "$skip"
  exit 0
else
  printf "\033[31mphase 4: FAIL (%d/%d passed, %d failed, %d skipped)\033[0m\n" "$pass" "$total" "$fail" "$skip"
  exit 1
fi
