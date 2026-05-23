#!/usr/bin/env bash
# vps-harden.sh — one-shot VPS bootstrap + hardening.
#
# Run on a fresh Ubuntu 24.04 LTS box as root, AFTER you have:
#   - logged in once as root via SSH with the key you uploaded at
#     provisioning time, and
#   - opened a SECOND SSH session in another terminal as a safety net
#     (do NOT close that second window until you have verified the
#     non-root user can log in).
#
# Usage (on the VPS):
#   scp scripts/vps-harden.sh root@<VPS-IP>:/root/
#   ssh root@<VPS-IP>
#   bash /root/vps-harden.sh <username>            # default: shisuke
#
# What it does (idempotent — safe to re-run):
#   1. Create a non-root sudo user and copy root's authorized_keys.
#   2. apt update + apt upgrade.
#   3. Install ufw + fail2ban.
#   4. Open ports 22 (ssh) / 80 (http) / 443 (https) / 8000 (Coolify UI).
#   5. Disable root SSH and password auth.
#   6. Restart sshd + enable fail2ban.
#
# SAFETY:
#   - This script never disables your existing SSH session.
#   - It does NOT close port 22.
#   - If the non-root user cannot log in after the script finishes,
#     YOUR ROOT SESSION IS STILL OPEN — fix authorized_keys before
#     closing it. Once root SSH is denied, you cannot get back in
#     without provider console access.
set -euo pipefail

USER_NAME="${1:-shisuke}"

require_root() {
  if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: run as root (sudo -i first)" >&2
    exit 1
  fi
}

ensure_user() {
  if id "$USER_NAME" >/dev/null 2>&1; then
    echo "user '$USER_NAME' exists — skipping useradd"
  else
    adduser --disabled-password --gecos "" "$USER_NAME"
  fi
  usermod -aG sudo "$USER_NAME"

  install -d -m 700 -o "$USER_NAME" -g "$USER_NAME" "/home/$USER_NAME/.ssh"
  if [ ! -f "/home/$USER_NAME/.ssh/authorized_keys" ]; then
    if [ -f /root/.ssh/authorized_keys ]; then
      install -m 600 -o "$USER_NAME" -g "$USER_NAME" \
        /root/.ssh/authorized_keys \
        "/home/$USER_NAME/.ssh/authorized_keys"
    else
      echo "ERROR: /root/.ssh/authorized_keys missing — cannot seed user key" >&2
      exit 1
    fi
  fi
}

apt_baseline() {
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get -y -qq upgrade
  apt-get -y -qq install ufw fail2ban
}

configure_ufw() {
  # Set defaults idempotently.
  ufw default deny incoming
  ufw default allow outgoing
  ufw allow 22/tcp comment 'ssh'
  ufw allow 80/tcp comment 'http (le challenge / coolify ingress)'
  ufw allow 443/tcp comment 'https'
  ufw allow 8000/tcp comment 'coolify ui (tighten by source IP later)'
  # `ufw enable` prompts unless --force.
  ufw --force enable
}

harden_ssh() {
  local cfg=/etc/ssh/sshd_config
  # Replace the directives with our desired values whether they were
  # present, commented out, or missing entirely.
  sed -ri 's|^[# ]*PermitRootLogin\b.*$|PermitRootLogin no|' "$cfg"
  grep -q '^PermitRootLogin no' "$cfg" || echo 'PermitRootLogin no' >> "$cfg"
  sed -ri 's|^[# ]*PasswordAuthentication\b.*$|PasswordAuthentication no|' "$cfg"
  grep -q '^PasswordAuthentication no' "$cfg" || echo 'PasswordAuthentication no' >> "$cfg"
  systemctl reload ssh || systemctl reload sshd
}

enable_fail2ban() {
  systemctl enable --now fail2ban
}

show_postchecks() {
  echo
  echo "──────────────────────────── post-checks ─────────────────────────────"
  echo "1) From your LAPTOP — do NOT close this root session yet:"
  echo "     ssh ${USER_NAME}@<this-vps-ip>"
  echo "   → must log in with your key, no password prompt."
  echo
  echo "2) Confirm root SSH is denied:"
  echo "     ssh root@<this-vps-ip>"
  echo "   → must show 'Permission denied (publickey)'."
  echo
  echo "3) Once both checks pass, close this root session safely."
  echo "──────────────────────────────────────────────────────────────────────"
}

main() {
  require_root
  ensure_user
  apt_baseline
  configure_ufw
  harden_ssh
  enable_fail2ban
  show_postchecks
}

main
