#!/usr/bin/env bash
# Dump an Open Brain database to a timestamped, gzipped SQL file.
#
# Coolify runs the scheduled production backups to R2 (Phase 8.2). This
# script is the on-demand / local equivalent and the source for the
# restore drill: it produces exactly the kind of artifact restore-test.sh
# consumes, so you can prove the whole backup→restore loop without
# waiting for the cron.
#
# pg_dump must match the SERVER major version, so we run it inside a
# pinned pgvector/pgvector:pg17 container rather than relying on whatever
# pg_dump the host has (which is often older and refuses to dump a newer
# server).
#
# Usage:
#   scripts/backup-db.sh                       # uses $DATABASE_URL or .env
#   scripts/backup-db.sh --dsn postgresql://... --out ./backups
#   DATABASE_URL=... scripts/backup-db.sh
set -euo pipefail

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"

dsn="${DATABASE_URL:-}"
out_dir="./backups"
pg_image="pgvector/pgvector:pg17"

while [ $# -gt 0 ]; do
  case "$1" in
    --dsn) dsn="$2"; shift 2 ;;
    --out) out_dir="$2"; shift 2 ;;
    -h|--help) grep -E '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$dsn" ] && [ -f .env ]; then
  dsn="$(awk -F= '/^DATABASE_URL=/{sub(/^DATABASE_URL=/,""); print; exit}' .env)"
fi
[ -n "$dsn" ] || { echo "error: no DSN (set DATABASE_URL or --dsn)" >&2; exit 2; }

# A DSN pointing at the compose-internal host 'postgres' is unreachable
# from a fresh container on the default bridge; rewrite to host.docker
# .internal so the dumper container can reach a host-published port.
dump_dsn="$dsn"
case "$dsn" in
  *@postgres:*) dump_dsn="${dsn/@postgres:/@host.docker.internal:}" ;;
  *@localhost:*) dump_dsn="${dsn/@localhost:/@host.docker.internal:}" ;;
  *@127.0.0.1:*) dump_dsn="${dsn/@127.0.0.1:/@host.docker.internal:}" ;;
esac

mkdir -p "$out_dir"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
out_file="$out_dir/openbrain-$stamp.sql.gz"

masked="$(printf '%s' "$dsn" | sed -E 's#(://[^:]+:)[^@]+@#\1***@#')"
echo "==> dumping $masked"
echo "==> -> $out_file"

# --add-host lets the container reach host-published Postgres ports.
docker run --rm --add-host host.docker.internal:host-gateway \
  "$pg_image" pg_dump --no-owner --no-privileges "$dump_dsn" \
  | gzip > "$out_file"

size="$(du -h "$out_file" | cut -f1)"
echo "==> done ($size)"

# Optional R2 upload when an rclone remote is configured.
if [ -n "${R2_REMOTE:-}" ] && command -v rclone >/dev/null 2>&1; then
  echo "==> uploading to $R2_REMOTE"
  rclone copy "$out_file" "$R2_REMOTE"
  echo "==> uploaded"
else
  echo "==> (R2 upload skipped: set R2_REMOTE and install rclone to enable)"
fi

echo "$out_file"
