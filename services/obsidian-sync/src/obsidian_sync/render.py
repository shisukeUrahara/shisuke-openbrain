"""Pure rendering: a documents row -> (relative path, file text).

No I/O. The main loop calls render_note() and writes the result.
Keeping this pure makes the path-safety + frontmatter logic trivially
unit-testable, which matters because path construction from
user-controlled titles is a classic source of traversal bugs.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class RenderedNote:
    relative_path: str   # e.g. "ax/article/How_X_works.md"
    text: str            # full file contents (frontmatter + body)


# Underscore is allowed because whitespace collapses to it first.
_UNSAFE_CHARS = re.compile(r"[^A-Za-z0-9._ -]")
_WHITESPACE = re.compile(r"\s+")


def safe_segment(value: str | None, *, fallback: str) -> str:
    """Turn an arbitrary string into a single safe path segment.

    Collapses any run of whitespace (spaces, tabs, newlines) to a
    single underscore FIRST — so a tab between words becomes a
    separator rather than being silently deleted — then strips
    characters outside [A-Za-z0-9._ -], trims to 80 chars, and
    forbids the traversal tokens '.' and '..'. Returns `fallback`
    if the result would be empty."""
    if not value or not value.strip():
        return fallback
    cleaned = _WHITESPACE.sub("_", value.strip())
    cleaned = _UNSAFE_CHARS.sub("", cleaned)
    cleaned = cleaned.strip("._ ")[:80].strip("._ ")
    if cleaned in ("", ".", ".."):
        return fallback
    return cleaned


def render_note(doc: dict[str, Any]) -> RenderedNote:
    """Render a documents row dict into a RenderedNote.

    `doc` must contain: id, title, kind, source, content_md,
    project, created_at. created_at may be a datetime or an ISO
    string.
    """
    project = safe_segment(doc.get("project"), fallback="inbox")
    kind = safe_segment(doc.get("kind"), fallback="misc")
    title = safe_segment(doc.get("title"), fallback=str(doc["id"])[:8])

    relative_path = f"{project}/{kind}/{title}.md"

    created = doc.get("created_at")
    if isinstance(created, datetime):
        created_iso = created.isoformat()
    elif isinstance(created, str):
        created_iso = created
    else:
        created_iso = ""

    frontmatter = (
        "---\n"
        f"doc_id: {doc['id']}\n"
        f"kind: {doc.get('kind') or ''}\n"
        f"source: {doc.get('source') or ''}\n"
        f"project: {doc.get('project') or 'inbox'}\n"
        f"created: {created_iso}\n"
        "---\n\n"
    )
    body = doc.get("content_md") or ""
    return RenderedNote(relative_path=relative_path, text=frontmatter + body)
