-- sql/modules/documents/011_chunks.sql
-- Purpose: Per-document chunked embeddings. One row per chunk of a
--          document, ordered by chunk_index. Used by search_chunks to
--          give the AI a passage-level context window instead of the
--          whole document for long-form content.
-- Phase:   10
-- Module:  documents
-- Idempotent: yes

create table if not exists chunks (
  id            uuid primary key default gen_random_uuid(),
  document_id   uuid not null references documents(id) on delete cascade,
  chunk_index   int  not null,
  content       text not null,
  embedding     vector(1536),
  metadata      jsonb not null default '{}'::jsonb,
  created_at    timestamptz not null default now()
);

-- One chunk_index per document.
create unique index if not exists chunks_document_index_uniq
  on chunks (document_id, chunk_index);

create index if not exists chunks_embedding_idx
  on chunks
  using hnsw (embedding vector_cosine_ops)
  with (m = 16, ef_construction = 64);

create index if not exists chunks_document_idx
  on chunks (document_id);

create index if not exists chunks_metadata_idx
  on chunks using gin (metadata);
