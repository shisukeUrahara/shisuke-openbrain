#!/usr/bin/env bats
# Phase 13 smoke — obsidian mirror on the live local stack.
#
# Prereqs:
#   docker compose --profile obsidian up -d
#   MODULE_OBSIDIAN_MIRROR_ENABLED=true in .env
#   notify trigger applied to the DB (sql/modules/obsidian/020_*.sql)
#
# Run:
#   bats tests/smoke/phase-13.bats

setup() {
  export DSN="postgresql://${POSTGRES_USER:-postgres}:${POSTGRES_PASSWORD:-devpass}@localhost:${POSTGRES_PORT:-5432}/${POSTGRES_DB:-openbrain}"
  export PROBE_TITLE="Bats Mirror Probe $$"
}

teardown() {
  psql "$DSN" -tAc "DELETE FROM documents WHERE title = '$PROBE_TITLE'" > /dev/null 2>&1 || true
}

@test "obsidian-sync container is up" {
  run docker compose --profile obsidian ps obsidian-sync
  [[ "$output" == *"Up"* ]] || [[ "$output" == *"running"* ]]
}

@test "obsidian-sync reports listening when flag is true" {
  flag=$(docker compose --profile obsidian exec -T obsidian-sync \
    sh -c 'echo "${MODULE_OBSIDIAN_MIRROR_ENABLED:-false}"' | tr -d '\r\n')
  if [ "$flag" != "true" ]; then
    skip "module is disabled in this container"
  fi
  run docker compose --profile obsidian logs --tail=20 obsidian-sync
  [[ "$output" == *"listening on new_document"* ]]
}

@test "notify trigger exists on documents" {
  run psql "$DSN" -tAc "SELECT count(*) FROM pg_trigger WHERE tgname='documents_notify_trigger'"
  [ "$status" -eq 0 ]
  [ "$output" = "1" ]
}

@test "inserting a document mirrors a markdown file into the vault" {
  psql "$DSN" -tAc "INSERT INTO documents (title, kind, source, content_md, project) VALUES ('$PROBE_TITLE', 'article', 'https://example.com/bats', 'bats body', 'batsproj')" > /dev/null
  # Give the listener a moment to write the file.
  sleep 3
  # Title sanitizes spaces -> underscores; the probe title contains a
  # PID so it is unique. Find any file under batsproj/article.
  run docker compose --profile obsidian exec -T obsidian-sync \
    sh -c "ls /vault/batsproj/article/ 2>/dev/null | wc -l"
  [ "$status" -eq 0 ]
  [ "$output" -ge 1 ]
}

@test "mirrored file carries frontmatter with doc_id" {
  psql "$DSN" -tAc "INSERT INTO documents (title, kind, content_md, project) VALUES ('$PROBE_TITLE fm', 'note', 'frontmatter check', 'batsproj')" > /dev/null
  sleep 3
  run docker compose --profile obsidian exec -T obsidian-sync \
    sh -c "grep -rl 'doc_id:' /vault/batsproj/ | head -1"
  [ "$status" -eq 0 ]
  [ -n "$output" ]
  # cleanup vault artifacts
  docker compose --profile obsidian exec -T obsidian-sync \
    sh -c "rm -rf /vault/batsproj" > /dev/null 2>&1 || true
  psql "$DSN" -tAc "DELETE FROM documents WHERE title LIKE '$PROBE_TITLE%'" > /dev/null 2>&1 || true
}
