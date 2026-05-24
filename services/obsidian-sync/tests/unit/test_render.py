"""Unit tests for obsidian_sync.render.

Pure logic: documents row -> (path, text). The path-safety tests
matter most — titles are user-controlled and a naive join would be
a directory-traversal hole.

Layer: unit
Phase: 13
Run:   pytest services/obsidian-sync/tests/unit/test_render.py -v
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from obsidian_sync.render import RenderedNote, render_note, safe_segment


# ──────────────────────────────────────────────────────────────────
# safe_segment
# ──────────────────────────────────────────────────────────────────

def test_safe_segment_passes_clean_titles():
    assert safe_segment("How pgvector works", fallback="x") == "How_pgvector_works"


def test_safe_segment_strips_unsafe_chars():
    assert safe_segment("a/b\\c:d*e?", fallback="x") == "abcde"


def test_safe_segment_collapses_whitespace():
    assert safe_segment("a    b\t\tc", fallback="x") == "a_b_c"


def test_safe_segment_empty_uses_fallback():
    assert safe_segment("", fallback="inbox") == "inbox"
    assert safe_segment("   ", fallback="inbox") == "inbox"
    assert safe_segment(None, fallback="inbox") == "inbox"


def test_safe_segment_traversal_tokens_use_fallback():
    assert safe_segment("..", fallback="safe") == "safe"
    assert safe_segment(".", fallback="safe") == "safe"
    # A title that is all slashes reduces to empty -> fallback.
    assert safe_segment("/////", fallback="safe") == "safe"


def test_safe_segment_truncates_long_titles():
    long = "a" * 200
    assert len(safe_segment(long, fallback="x")) <= 80


def test_safe_segment_strips_leading_trailing_dots_and_spaces():
    assert safe_segment("...hidden...", fallback="x") == "hidden"


# ──────────────────────────────────────────────────────────────────
# render_note
# ──────────────────────────────────────────────────────────────────

def _doc(**kw):
    base = {
        "id": "7f3c0000-0000-0000-0000-000000000001",
        "title": "Example Title",
        "kind": "article",
        "source": "https://example.com/x",
        "content_md": "# Heading\n\nbody",
        "project": "ax",
        "created_at": datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc),
    }
    base.update(kw)
    return base


def test_render_builds_project_kind_title_path():
    note = render_note(_doc())
    assert note.relative_path == "ax/article/Example_Title.md"


def test_render_defaults_project_to_inbox():
    note = render_note(_doc(project=None))
    assert note.relative_path.startswith("inbox/")


def test_render_defaults_kind_to_misc():
    note = render_note(_doc(kind=None))
    assert "/misc/" in note.relative_path


def test_render_title_falls_back_to_id_prefix():
    note = render_note(_doc(title=None))
    # First 8 chars of the id.
    assert note.relative_path.endswith("7f3c0000.md")


def test_render_includes_frontmatter():
    note = render_note(_doc())
    assert note.text.startswith("---\n")
    assert "doc_id: 7f3c0000-0000-0000-0000-000000000001" in note.text
    assert "kind: article" in note.text
    assert "source: https://example.com/x" in note.text
    assert "project: ax" in note.text
    assert "created: 2026-05-23T12:00:00+00:00" in note.text


def test_render_includes_body_after_frontmatter():
    note = render_note(_doc())
    assert note.text.endswith("# Heading\n\nbody")


def test_render_handles_iso_string_created_at():
    note = render_note(_doc(created_at="2026-01-01T00:00:00+00:00"))
    assert "created: 2026-01-01T00:00:00+00:00" in note.text


def test_render_handles_null_content():
    note = render_note(_doc(content_md=None))
    # Frontmatter present, empty body.
    assert note.text.endswith("---\n\n")


def test_render_traversal_title_cannot_escape():
    """A malicious title must not produce a path with '..' segments."""
    note = render_note(_doc(title="../../etc/passwd"))
    assert ".." not in note.relative_path.split("/")
