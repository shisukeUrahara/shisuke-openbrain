-- sql/modules/documents/010_documents.sql
-- Purpose: Long-form content store. One row per ingested document
--          (article, PDF, video transcript, voice note). The document
--          carries the canonical markdown, an optional summary, and an
--          embedding of the summary so document-level semantic search
--          works without re-walking every chunk.
-- Phase:   10
-- Module:  documents
-- Idempotent: yes

create table if not exists documents (
  id                  uuid primary key default gen_random_uuid(),
  title               text not null,
  kind                text not null,        -- 'article' | 'pdf' | 'youtube' | 'voice' | 'image' | etc.
  source              text,                 -- URL, file path, or telegram message ref
  content_md          text,                 -- full markdown body
  summary             text,                 -- optional short summary
  summary_embedding   vector(1536),         -- embedding of summary OR truncated content
  metadata            jsonb not null default '{}'::jsonb,
  project             text,                 -- soft tag for cross-project queries
  sha256              text,                 -- content hash for incremental ingestion
  created_at          timestamptz not null default now(),
  updated_at          timestamptz not null default now()
);

-- sha256 is unique when present; null is allowed for documents that
-- pre-date the dedup column (none in practice but we stay safe).
create unique index if not exists documents_sha256_uniq
  on documents (sha256)
  where sha256 is not null;

create index if not exists documents_summary_embedding_idx
  on documents
  using hnsw (summary_embedding vector_cosine_ops)
  with (m = 16, ef_construction = 64);

create index if not exists documents_kind_idx     on documents (kind);
create index if not exists documents_project_idx  on documents (project);
create index if not exists documents_created_idx  on documents (created_at desc);
create index if not exists documents_metadata_idx on documents using gin (metadata);

drop trigger if exists documents_updated_at on documents;
create trigger documents_updated_at
  before update on documents
  for each row
  execute function update_updated_at();
