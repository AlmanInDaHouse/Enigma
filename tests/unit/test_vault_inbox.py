"""Tests para `write_notes_to_inbox` (T-111)."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from enigma.config import settings
from enigma.models.note import Note, NoteSource
from enigma.vault.writer import write_notes_to_inbox


def _note(title: str = "Una idea atómica", body: str = "Cuerpo de la nota.") -> Note:
    return Note(
        id=uuid4(),
        title=title,
        body=body,
        tags=["t"],
        source=NoteSource(call_id=uuid4(), timestamp_start=0.0, timestamp_end=1.0),
        content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        extracted_by="qwen2.5:7b",
        created_at=datetime.now(tz=UTC),
    )


def test_write_notes_creates_inbox_dir(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    assert not inbox.exists()
    write_notes_to_inbox([_note()], vault_path=tmp_path)
    assert inbox.is_dir()


def test_write_notes_writes_one_file_per_note(tmp_path: Path) -> None:
    notes = [_note(title=f"Idea {i}") for i in range(3)]
    paths = write_notes_to_inbox(notes, vault_path=tmp_path)
    assert len(paths) == 3
    for path in paths:
        assert path.is_file()
        assert path.parent.name == "inbox"


def test_write_notes_uses_settings_vault_when_no_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin `vault_path` explícito, usa `settings.enigma_vault_path`."""
    monkeypatch.setattr(settings, "enigma_vault_path", tmp_path)
    paths = write_notes_to_inbox([_note()])
    assert paths[0].parent == tmp_path / "inbox"


def test_write_notes_with_empty_list_returns_empty(tmp_path: Path) -> None:
    paths = write_notes_to_inbox([], vault_path=tmp_path)
    assert paths == []
    # Ni siquiera crea la carpeta inbox si no hay notas.
    assert not (tmp_path / "inbox").exists()


def test_write_notes_is_idempotent_per_note(tmp_path: Path) -> None:
    """Reingerir las mismas notas no aumenta el número de ficheros."""
    note = _note()
    write_notes_to_inbox([note], vault_path=tmp_path)
    write_notes_to_inbox([note], vault_path=tmp_path)
    files = list((tmp_path / "inbox").glob("*.md"))
    assert len(files) == 1


def test_write_notes_files_have_frontmatter_block(tmp_path: Path) -> None:
    paths = write_notes_to_inbox([_note(title="Captación padel")], vault_path=tmp_path)
    content = paths[0].read_text(encoding="utf-8")
    assert content.startswith("---\n")
    assert "# Captación padel" in content
