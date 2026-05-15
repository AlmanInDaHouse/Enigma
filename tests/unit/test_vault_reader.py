"""Tests para `enigma.vault.reader` (T-114)."""

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from enigma.models.note import Note, NoteSource
from enigma.vault.reader import list_vault_notes, read_note_summary
from enigma.vault.writer import upsert_note


def _note(
    *,
    title: str = "Idea atómica",
    body: str = "Cuerpo de la nota.",
    created_at: datetime | None = None,
    status: str = "draft",
) -> Note:
    return Note(
        id=uuid4(),
        title=title,
        body=body,
        tags=["tag-uno", "tag-dos"],
        source=NoteSource(call_id=uuid4(), timestamp_start=0.0, timestamp_end=1.0),
        content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        status=status,  # type: ignore[arg-type]
        extracted_by="qwen2.5:7b",
        created_at=created_at if created_at is not None else datetime.now(tz=UTC),
    )


# ── read_note_summary ───────────────────────────────────────────────────────


def test_read_summary_parses_a_real_written_note(tmp_path: Path) -> None:
    """Round-trip: una nota escrita por `upsert_note` se lee con `read_note_summary`."""
    note = _note(title="Captación padel", status="validated")
    path = upsert_note(note, vault_dir=tmp_path)
    summary = read_note_summary(path)
    assert summary is not None
    assert summary.note_id == note.id
    assert summary.title == "Captación padel"
    assert summary.call_id == note.source.call_id
    assert summary.status == "validated"
    assert summary.tags == ["tag-uno", "tag-dos"]


def test_read_summary_returns_none_for_plain_text(tmp_path: Path) -> None:
    bad = tmp_path / "plain.md"
    bad.write_text("Solo texto, sin frontmatter.", encoding="utf-8")
    assert read_note_summary(bad) is None


def test_read_summary_returns_none_when_source_missing(tmp_path: Path) -> None:
    path = tmp_path / "nosource.md"
    path.write_text(
        f"---\nid: {uuid4()}\ntitle: Sin source\n"
        "created_at: 2026-05-14T00:00:00+00:00\n---\n\nbody\n",
        encoding="utf-8",
    )
    assert read_note_summary(path) is None


def test_read_summary_returns_none_when_id_missing(tmp_path: Path) -> None:
    path = tmp_path / "noid.md"
    path.write_text(
        "---\ntitle: Sin id\nsource:\n  call_id: "
        f"{uuid4()}\ncreated_at: 2026-05-14T00:00:00+00:00\n---\n\nbody\n",
        encoding="utf-8",
    )
    assert read_note_summary(path) is None


# ── list_vault_notes ────────────────────────────────────────────────────────


def test_list_reads_both_inbox_and_notes(tmp_path: Path) -> None:
    upsert_note(_note(title="En inbox"), vault_dir=tmp_path / "inbox")
    upsert_note(_note(title="En notes"), vault_dir=tmp_path / "notes")
    summaries = list_vault_notes(vault_path=tmp_path)
    assert {s.title for s in summaries} == {"En inbox", "En notes"}


def test_list_empty_vault_returns_empty(tmp_path: Path) -> None:
    assert list_vault_notes(vault_path=tmp_path) == []


def test_list_filters_by_since(tmp_path: Path) -> None:
    old = _note(title="Vieja", created_at=datetime.now(tz=UTC) - timedelta(days=30))
    recent = _note(title="Reciente", created_at=datetime.now(tz=UTC))
    upsert_note(old, vault_dir=tmp_path / "inbox")
    upsert_note(recent, vault_dir=tmp_path / "inbox")
    cutoff = datetime.now(tz=UTC) - timedelta(days=7)
    summaries = list_vault_notes(vault_path=tmp_path, since=cutoff)
    assert [s.title for s in summaries] == ["Reciente"]


def test_list_sorted_by_created_at_descending(tmp_path: Path) -> None:
    now = datetime.now(tz=UTC)
    for title, delta in [("A", 2), ("B", 1), ("C", 0)]:
        upsert_note(
            _note(title=title, created_at=now - timedelta(days=delta)),
            vault_dir=tmp_path / "inbox",
        )
    summaries = list_vault_notes(vault_path=tmp_path)
    assert [s.title for s in summaries] == ["C", "B", "A"]


def test_list_ignores_invalid_files(tmp_path: Path) -> None:
    upsert_note(_note(title="Buena"), vault_dir=tmp_path / "inbox")
    (tmp_path / "inbox" / "ruido.md").write_text("sin frontmatter", encoding="utf-8")
    summaries = list_vault_notes(vault_path=tmp_path)
    assert [s.title for s in summaries] == ["Buena"]
