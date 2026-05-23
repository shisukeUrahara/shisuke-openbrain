-- sql/002_match_thoughts.sql
-- Purpose: Semantic search RPC. Takes a query embedding plus optional
--          metadata filter, returns the top-N rows by cosine similarity
--          where similarity > match_threshold. Cosine similarity is
--          (1 - cosine_distance), so higher is closer.
-- Phase:   01
-- Module:  core
-- Idempotent: yes (CREATE OR REPLACE)

create or replace function match_thoughts(
  query_embedding  vector(1536),
  match_threshold  float   default 0.7,
  match_count      int     default 10,
  filter           jsonb   default '{}'::jsonb
)
returns table (
  id          uuid,
  content     text,
  metadata    jsonb,
  similarity  float,
  created_at  timestamptz
)
language plpgsql
stable
as $$
begin
  return query
  select
    t.id,
    t.content,
    t.metadata,
    1 - (t.embedding <=> query_embedding) as similarity,
    t.created_at
  from thoughts t
  where t.embedding is not null
    and 1 - (t.embedding <=> query_embedding) > match_threshold
    and (filter = '{}'::jsonb or t.metadata @> filter)
  order by t.embedding <=> query_embedding
  limit match_count;
end;
$$;
