"""Tests para la detección de notas huérfanas (T-207)."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from enigma.config import settings
from enigma.models.note import Note, NoteSource
from enigma.vault.linker import (
    WikilinkSuggestion,
    apply_wikilinks,
    has_wikilinks,
    mark_orphans,
)
from enigma.vault.reader import read_note
from enigma.vault.writer import upsert_note


def _note(title: str = "Idea", body: str = "Cuerpo de la nota.") -> Note:
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


# ── has_wikilinks ───────────────────────────────────────────────────────────


def test_has_wikilinks_detects_a_link() -> None:
    assert has_wikilinks("texto con [[un-enlace|Título]] dentro")


def test_has_wikilinks_false_without_links() -> None:
    assert not has_wikilinks("texto plano sin enlaces")


def test_has_wikilinks_false_on_single_brackets() -> None:
    assert not has_wikilinks("esto [no] es un wikilink")


# ── mark_orphans ────────────────────────────────────────────────────────────


def test_mark_orphans_tags_note_without_wikilinks(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    upsert_note(_note(title="Sin conexiones"), vault_dir=inbox)

    report = mark_orphans(vault_path=tmp_path)

    assert report.total_notes == 1
    assert report.orphans == 1
    assert report.newly_tagged == 1
    # La nota reescrita lleva el tag orphan.
    note_file = next(inbox.glob("*.md"))
    reloaded = read_note(note_file)
    assert reloaded is not None
    assert "orphan" in reloaded.tags


def test_mark_orphans_skips_note_with_wikilinks(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    note = _note(title="Con conexiones")
    suggestion = WikilinkSuggestion(target_note_id=uuid4(), target_title="Vecina", score=0.9)
    apply_wikilinks(note, [suggestion], vault_dir=inbox)

    report = mark_orphans(vault_path=tmp_path)

    assert report.total_notes == 1
    assert report.orphans == 0
    assert report.newly_tagged == 0


def test_mark_orphans_counts_mix(tmp_path: Path) -> None:
    inbox = tmp_path / "inbox"
    upsert_note(_note(title="Huerfana A"), vault_dir=inbox)
    upsert_note(_note(title="Huerfana B"), vault_dir=inbox)
    apply_wikilinks(
        _note(title="Conectada"),
        [WikilinkSuggestion(target_note_id=uuid4(), target_title="X", score=0.9)],
        vault_dir=inbox,
    )

    report = mark_orphans(vault_path=tmp_path)

    assert report.total_notes == 3
    assert report.orphans == 2
    assert report.newly_tagged == 2


def test_mark_orphans_is_idempotent(tmp_path: Path) -> None:
    """Reejecutar no vuelve a marcar una nota que ya tiene el tag orphan."""
    inbox = tmp_path / "inbox"
    upsert_note(_note(title="Sin conexiones"), vault_dir=inbox)

    first = mark_orphans(vault_path=tmp_path)
    second = mark_orphans(vault_path=tmp_path)

    assert first.newly_tagged == 1
    assert second.orphans == 1  # sigue siendo huérfana
    assert second.newly_tagged == 0  # pero ya estaba marcada


def test_mark_orphans_empty_vault(tmp_path: Path) -> None:
    report = mark_orphans(vault_path=tmp_path)
    assert report.total_notes == 0
    assert report.orphans == 0
    assert report.newly_tagged == 0


def test_mark_orphans_uses_settings_vault(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "enigma_vault_path", tmp_path)
    upsert_note(_note(), vault_dir=tmp_path / "inbox")
    report = mark_orphans()
    assert report.total_notes == 1
