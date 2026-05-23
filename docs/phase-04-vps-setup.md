# Phase 4 — VPS Provisioning + Hardening (Operator Guide)

This phase is mostly things **you** do: provision a VPS, point DNS, run an SSH-side hardening script, and verify from your laptop. The repo ships the harden script (`scripts/vps-harden.sh`) and the laptop-side bats smoke suite (`tests/smoke/phase-04.bats`); everything else is at the provider control panel and the SSH command line.

Total time: ~45 minutes start to finish.

---

## Step 1 — Provision the VPS

Vendor: **Hetzner Cloud** (recommended for India region, ~€4.51/mo). DigitalOcean, Linode, or Vultr work the same way.

1. Sign in to https://console.hetzner.cloud/ and click **Add Server**.
2. **Location**: pick the region closest to you. Helsinki / Nuremberg are fine from India.
3. **Image**: **Ubuntu 24.04 LTS**.
4. **Type**: **CX22** (2 vCPU, 4 GB RAM, 40 GB disk). Upgrade to **CX32** later if you plan to host audio/PDF workers on the same box.
5. **Networking**: IPv4 + IPv6 both enabled.
6. **SSH keys**: upload your laptop's public key (`cat ~/.ssh/id_ed25519.pub`). If you do not have one yet, run `ssh-keygen -t ed25519` first.
7. **Name**: `openbrain-vps` (or your choice).
8. Click **Create & Buy now**.

Save the **IPv4 address** into your password manager as `VPS_IP`.

---

## Step 2 — Point DNS at the VPS

You need a domain you own. If you do not have one yet, Cloudflare Registrar registers `.com`s for ~$10/yr at cost.

1. Sign in to https://dash.cloudflare.com.
2. Open your domain → **DNS → Records → Add record**.
3. **Type**: A. **Name**: `brain` (so the FQDN becomes `brain.<yourdomain>`). **IPv4 address**: the VPS IP. **Proxy status**: **DNS only (grey cloud)**. Coolify will issue Let's Encrypt directly in Phase 5 and an orange-cloud proxy interferes with that handshake unless you switch to Full (Strict).
4. Add an AAAA record for IPv6 the same way (optional).
5. From your laptop:
   ```bash
   dig +short brain.<yourdomain>
   ```
   Must return the VPS IP. DNS propagation usually takes a few minutes. If it does not show up in 15, double-check the record.

Save the FQDN as `VPS_HOST` in your notes.

---

## Step 3 — Run the harden script

> ⚠️ **Keep two SSH terminals open through this step.** The script disables root SSH at the end. If your non-root user cannot log in for any reason, you need the second root session as a safety net.

From your laptop:

```bash
# Copy the script to the VPS
scp scripts/vps-harden.sh root@<VPS-IP>:/root/

# Open a SAFETY-NET root SSH in one terminal — leave it open
ssh root@<VPS-IP>

# In a SECOND terminal, the work session:
ssh root@<VPS-IP>
bash /root/vps-harden.sh shisuke    # or your preferred username
```

The script (idempotent — safe to re-run):

1. Creates the non-root user `shisuke` (or the name you pass).
2. Copies root's `authorized_keys` so your laptop key works for both.
3. `apt update + apt upgrade -y`.
4. Installs `ufw` and `fail2ban`.
5. Opens ports 22 / 80 / 443 / 8000.
6. Disables root SSH.
7. Disables password auth.
8. Enables `fail2ban`.

When it finishes, it prints a 3-step post-check banner.

---

## Step 4 — Verify hardening from your laptop

In a **third** terminal, from your laptop (not the VPS):

```bash
ssh shisuke@<VPS-IP>            # MUST succeed without a password
ssh root@<VPS-IP>               # MUST fail with 'Permission denied (publickey)'
```

Only once both checks pass should you close the safety-net root session from Step 3.

---

## Step 5 — Run the automated smoke suite

From your laptop:

```bash
export VPS_HOST="brain.<yourdomain>"
export VPS_IP="<vps ipv4>"
export VPS_USER=shisuke

bats tests/smoke/phase-04.bats
```

Expect 9/9 passing. The suite covers:

* DNS resolves the FQDN.
* The A record value matches `VPS_IP`.
* Root SSH is denied.
* The non-root user can SSH by IP and by hostname.
* `ufw status` reports active.
* `fail2ban` is `active`.
* `/etc/ssh/sshd_config` has `PermitRootLogin no` and `PasswordAuthentication no`.

When those are green, run the full Phase 4 acceptance gate:

```bash
bash scripts/verify-phase-04.sh
```

Expect `phase 4: OK`.

---

## Things that go wrong, and what to do

| Symptom | Fix |
|---|---|
| `dig +short` returns nothing | DNS not propagated yet — wait 15 min, retry from `dig @1.1.1.1`. |
| Non-root SSH prompts for a password | `authorized_keys` is not in `/home/<user>/.ssh/`, or its permissions are wrong. Fix in the safety-net root session: `chmod 700 ~user/.ssh; chmod 600 ~user/.ssh/authorized_keys`. |
| Cannot reach the VPS at all | Firewall denied your laptop IP, or Hetzner is rate-limiting after too many auth attempts. Wait, then try again. Worst case: provider console gives you out-of-band access. |
| `ufw status` says inactive | Re-run `bash /root/vps-harden.sh` — `configure_ufw` is idempotent. |
| Cloudflare orange-clouded the A record by mistake | Toggle it back to DNS-only. Otherwise Let's Encrypt in Phase 5 fails the HTTP-01 challenge. |

---

## When you are done

* Update `plan/RUNBOOK.md` with the VPS IP, the FQDN you chose, and the date you provisioned.
* Save `VPS_HOST`, `VPS_IP`, `VPS_USER` in your password manager.
* Phase 5 — installing Coolify on the box — starts immediately after.
