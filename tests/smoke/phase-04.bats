#!/usr/bin/env bats
# Phase 4 outside-in smoke — runs on your LAPTOP, not the VPS.
#
# These tests prove DNS is wired, the non-root user can log in, and
# root SSH is denied. Skip with a clear message when the necessary
# environment is not configured.
#
# Required environment variables:
#   VPS_HOST     fully qualified hostname pointed at the VPS
#                (e.g. brain.yourdomain.com)
#   VPS_IP       IPv4 address of the VPS (used to bypass DNS for
#                the root SSH test)
#   VPS_USER     non-root user created by vps-harden.sh (default: shisuke)
#
# Run:
#   VPS_HOST=brain.example.com VPS_IP=1.2.3.4 VPS_USER=shisuke \
#       bats tests/smoke/phase-04.bats

setup() {
  : "${VPS_HOST:?export VPS_HOST=<fqdn>}"
  : "${VPS_IP:?export VPS_IP=<ipv4>}"
  : "${VPS_USER:=shisuke}"
  export SSH_OPTS="-o BatchMode=yes -o ConnectTimeout=5 -o StrictHostKeyChecking=accept-new"
}

@test "DNS resolves VPS_HOST" {
  run dig +short "$VPS_HOST"
  [ "$status" -eq 0 ]
  [ -n "$output" ]
}

@test "DNS A record points at VPS_IP" {
  run bash -c "dig +short A '$VPS_HOST' | head -1"
  [ "$status" -eq 0 ]
  [ "$output" = "$VPS_IP" ]
}

@test "root SSH is denied" {
  run ssh $SSH_OPTS "root@$VPS_IP" true
  [ "$status" -ne 0 ]
}

@test "non-root SSH (by IP) succeeds with key" {
  run ssh $SSH_OPTS "$VPS_USER@$VPS_IP" true
  [ "$status" -eq 0 ]
}

@test "non-root SSH (by hostname) succeeds with key" {
  run ssh $SSH_OPTS "$VPS_USER@$VPS_HOST" true
  [ "$status" -eq 0 ]
}

@test "ufw is active on the VPS" {
  run ssh $SSH_OPTS "$VPS_USER@$VPS_IP" "sudo -n ufw status | head -1"
  [ "$status" -eq 0 ]
  [[ "$output" == *"active"* ]]
}

@test "fail2ban service is active on the VPS" {
  run ssh $SSH_OPTS "$VPS_USER@$VPS_IP" "systemctl is-active fail2ban"
  [ "$status" -eq 0 ]
  [ "$output" = "active" ]
}

@test "SSH config disables root login" {
  run ssh $SSH_OPTS "$VPS_USER@$VPS_IP" \
    "sudo -n grep -E '^PermitRootLogin' /etc/ssh/sshd_config | head -1"
  [ "$status" -eq 0 ]
  [[ "$output" == *"PermitRootLogin no"* ]]
}

@test "SSH config disables password auth" {
  run ssh $SSH_OPTS "$VPS_USER@$VPS_IP" \
    "sudo -n grep -E '^PasswordAuthentication' /etc/ssh/sshd_config | head -1"
  [ "$status" -eq 0 ]
  [[ "$output" == *"PasswordAuthentication no"* ]]
}
