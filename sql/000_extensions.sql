-- sql/000_extensions.sql
-- Purpose: Enable required Postgres extensions (pgvector for embeddings,
--          pg_trgm for fuzzy text search, uuid-ossp for UUID generation).
-- Phase:   01
-- Module:  core
-- Idempotent: yes

create extension if not exists vector;
create extension if not exists pg_trgm;
create extension if not exists "uuid-ossp";
