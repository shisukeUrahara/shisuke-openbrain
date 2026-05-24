-- sql/modules/obsidian/020_notify_document.sql
-- Purpose: Fire a Postgres NOTIFY on the 'new_document' channel
--          whenever a row is inserted into documents, so the
--          obsidian-sync listener can mirror it to a markdown vault
--          without polling. Payload is a small JSON object with the
--          document id (the listener fetches the rest).
-- Phase:   13
-- Module:  obsidian
-- Idempotent: yes (CREATE OR REPLACE + DROP TRIGGER IF EXISTS)

create or replace function notify_new_document()
returns trigger
language plpgsql
as $$
begin
  perform pg_notify(
    'new_document',
    json_build_object(
      'id',      new.id,
      'title',   new.title,
      'kind',    new.kind,
      'project', new.project
    )::text
  );
  return new;
end;
$$;

drop trigger if exists documents_notify_trigger on documents;
create trigger documents_notify_trigger
  after insert on documents
  for each row
  execute function notify_new_document();
