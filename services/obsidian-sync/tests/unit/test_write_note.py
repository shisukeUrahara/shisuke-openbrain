"""Unit tests for obsidian_sync.main.write_note.

The only impure seam in the service. Verifies files land at the
right place under the vault, parent dirs are created, overwrite
semantics, and — critically — that a crafted relative path cannot
escape the vault.

Layer: unit
Phase: 13
Run:   pytest services/obsidian-sync/tests/unit/test_write_note.py -v
"""
from __future__ import annotations

from pathlib import Path

import pytest

from obsidian_sync.main import write_note
from obsidian_sync.render import RenderedNote


def test_write_creates_nested_dirs_and_file(tmp_path: Path):
    note = RenderedNote(relative_path="ax/article/My_Note.md", text="hello")
    written = write_note(tmp_path, note)
    assert written is True
    target = tmp_path / "ax" / "article" / "My_Note.md"
    assert target.is_file()
    assert target.read_text() == "hello"


def test_write_overwrite_true_replaces_existing(tmp_path: Path):
    note1 = RenderedNote(relative_path="a/b/x.md", text="first")
    note2 = RenderedNote(relative_path="a/b/x.md", text="second")
    write_note(tmp_path, note1)
    written = write_note(tmp_path, note2, overwrite=True)
    assert written is True
    assert (tmp_path / "a" / "b" / "x.md").read_text() == "second"


def test_write_overwrite_false_keeps_existing(tmp_path: Path):
    note1 = RenderedNote(relative_path="a/b/x.md", text="first")
    note2 = RenderedNote(relative_path="a/b/x.md", text="second")
    write_note(tmp_path, note1)
    written = write_note(tmp_path, note2, overwrite=False)
    assert written is False
    assert (tmp_path / "a" / "b" / "x.md").read_text() == "first"


def test_write_refuses_path_outside_vault(tmp_path: Path):
    """A relative path that resolves outside the vault must be
    refused even if it somehow slipped past render.safe_segment."""
    note = RenderedNote(relative_path="../escape.md", text="evil")
    with pytest.raises(ValueError, match="outside vault"):
        write_note(tmp_path, note)


def test_write_refuses_absolute_path_escape(tmp_path: Path):
    note = RenderedNote(relative_path="../../etc/passwd", text="evil")
    with pytest.raises(ValueError, match="outside vault"):
        write_note(tmp_path, note)
