-- sql/modules/documents/012_match_chunks.sql
-- Purpose: Semantic search over chunks. Returns the top-N chunks by
--          cosine similarity to a query embedding, with the
--          parent document's title and source attached for citation.
--          Optional filters narrow to a single document or project.
-- Phase:   10
-- Module:  documents
-- Idempotent: yes (CREATE OR REPLACE)

create or replace function match_chunks(
  query_embedding   vector(1536),
  match_threshold   float   default 0.5,
  match_count       int     default 8,
  filter_document   uuid    default null,
  filter_project    text    default null
)
returns table (
  id              uuid,
  document_id     uuid,
  document_title  text,
  document_source text,
  chunk_index     int,
  content         text,
  metadata        jsonb,
  similarity      float,
  created_at      timestamptz
)
language plpgsql
stable
as $$
begin
  return query
  select
    c.id,
    c.document_id,
    d.title           as document_title,
    d.source          as document_source,
    c.chunk_index,
    c.content,
    c.metadata,
    1 - (c.embedding <=> query_embedding) as similarity,
    c.created_at
  from chunks c
  join documents d on d.id = c.document_id
  where c.embedding is not null
    and 1 - (c.embedding <=> query_embedding) > match_threshold
    and (filter_document is null or c.document_id = filter_document)
    and (filter_project  is null or d.project = filter_project)
  order by c.embedding <=> query_embedding
  limit match_count;
end;
$$;
