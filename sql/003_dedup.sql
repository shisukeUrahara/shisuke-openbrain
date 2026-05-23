-- sql/003_dedup.sql
-- Purpose: Content-fingerprint dedup. Adds a SHA-256 column over the
--          normalized content (lowercased, whitespace-collapsed) plus a
--          unique partial index. The upsert_thought function inserts new
--          rows and merges metadata on existing fingerprints — capturing
--          the same content twice is a no-op for the row itself but does
--          update updated_at and merge any new metadata keys.
-- Phase:   01
-- Module:  core
-- Idempotent: yes

alter table thoughts
  add column if not exists content_fingerprint text;

create unique index if not exists thoughts_fingerprint_uniq
  on thoughts (content_fingerprint)
  where content_fingerprint is not null;

create or replace function upsert_thought(
  p_content  text,
  p_payload  jsonb default '{}'::jsonb
)
returns jsonb
language plpgsql
as $$
declare
  v_fingerprint  text;
  v_id           uuid;
begin
  -- Normalize: lower-case, collapse whitespace, then SHA-256 hex.
  v_fingerprint := encode(
    sha256(
      convert_to(
        lower(trim(regexp_replace(p_content, '\s+', ' ', 'g'))),
        'UTF8'
      )
    ),
    'hex'
  );

  insert into thoughts (content, content_fingerprint, metadata)
  values (
    p_content,
    v_fingerprint,
    coalesce(p_payload -> 'metadata', '{}'::jsonb)
  )
  on conflict (content_fingerprint) where content_fingerprint is not null
  do update
    set updated_at = now(),
        metadata   = thoughts.metadata || coalesce(excluded.metadata, '{}'::jsonb)
  returning id into v_id;

  return jsonb_build_object(
    'id', v_id,
    'fingerprint', v_fingerprint
  );
end;
$$;
