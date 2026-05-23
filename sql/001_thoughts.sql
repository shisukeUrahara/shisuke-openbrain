-- sql/001_thoughts.sql
-- Purpose: Core thoughts table — one row per captured piece of text with
--          its embedding, metadata, and timestamps. The HNSW vector index
--          enables fast cosine-similarity search. The GIN index on metadata
--          enables filter-by-key queries. The btree on created_at supports
--          chronological browse.
-- Phase:   01
-- Module:  core
-- Idempotent: yes

create table if not exists thoughts (
  id          uuid primary key default gen_random_uuid(),
  content     text not null,
  embedding   vector(1536),
  metadata    jsonb not null default '{}'::jsonb,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now()
);

create index if not exists thoughts_embedding_idx
  on thoughts
  using hnsw (embedding vector_cosine_ops)
  with (m = 16, ef_construction = 64);

create index if not exists thoughts_metadata_idx
  on thoughts
  using gin (metadata);

create index if not exists thoughts_created_at_idx
  on thoughts (created_at desc);

create or replace function update_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

drop trigger if exists thoughts_updated_at on thoughts;
create trigger thoughts_updated_at
  before update on thoughts
  for each row
  execute function update_updated_at();
