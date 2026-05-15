"""Tests para `enigma.vault.writer` (T-110)."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

from enigma.models.note import Note, NoteSource
from enigma.vault.writer import SHORT_ID_LEN, note_filename, upsert_note


def _note(
    *,
    note_id: UUID | None = None,
    title: str = "Estrategia de captación para clubs de padel",
    body: str = "Cuerpo de la nota.",
) -> Note:
    return Note(
        id=note_id if note_id is not None else uuid4(),
        title=title,
        body=body,
        tags=["t"],
        source=NoteSource(call_id=uuid4(), timestamp_start=0.0, timestamp_end=1.0),
        content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        extracted_by="qwen2.5:7b",
        created_at=datetime.now(tz=UTC),
    )


# ── note_filename ───────────────────────────────────────────────────────────


def test_filename_is_deterministic_for_same_note() -> None:
    note = _note()
    assert note_filename(note) == note_filename(note)


def test_filename_contains_short_id() -> None:
    note_id = UUID("12345678-1234-5678-1234-567812345678")
    note = _note(note_id=note_id)
    name = note_filename(note)
    assert note_id.hex[:SHORT_ID_LEN] in name
    assert name.endswith(".md")


def test_filename_slugs_title_to_kebab_lowercase() -> None:
    note = _note(title="Estrategia de Captación para Clubs de Padel")
    name = note_filename(note)
    assert name.startswith("estrategia-de-captacion-para-clubs-de-padel-")


def test_filename_strips_special_chars() -> None:
    note = _note(title="¡Captación rápida! Plan A & B (2026)")
    name = note_filename(note)
    for forbidden in ("!", "(", ")", "&", "¡"):
        assert forbidden not in name


def test_filename_uses_untitled_fallback_for_empty_slug() -> None:
    """Título con solo espacios o solo símbolos → slug vacío → fallback."""
    note = _note(title="   ")
    name = note_filename(note)
    assert name.startswith("untitled-")


def test_filename_bounded_by_max_slug_len() -> None:
    """Títulos muy largos se truncan; el filename total queda < ~80 chars."""
    note = _note(title="palabra " * 50)  # ~400 chars
    name = note_filename(note)
    # 60 chars slug + 1 ('-') + 8 short_id + 3 ('.md') = 72 max
    assert len(name) <= 75


def test_filenames_differ_when_only_id_differs() -> None:
    a = _note(note_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"), title="Idea")
    b = _note(note_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"), title="Idea")
    assert note_filename(a) != note_filename(b)


def test_filenames_differ_when_only_title_differs() -> None:
    same_id = uuid4()
    a = _note(note_id=same_id, title="Idea A")
    b = _note(note_id=same_id, title="Idea B")
    assert note_filename(a) != note_filename(b)


# ── upsert_note ─────────────────────────────────────────────────────────────


def test_upsert_creates_file_with_expected_name(tmp_path: Path) -> None:
    note = _note()
    path = upsert_note(note, vault_dir=tmp_path)
    assert path == tmp_path / note_filename(note)
    assert path.is_file()


def test_upsert_writes_full_markdown(tmp_path: Path) -> None:
    note = _note(title="Idea con cuerpo", body="Cuerpo concreto y único.")
    path = upsert_note(note, vault_dir=tmp_path)
    content = path.read_text(encoding="utf-8")
    assert content.startswith("---\n")
    assert "# Idea con cuerpo" in content
    assert "Cuerpo concreto y único." in content


def test_upsert_creates_parent_dir_if_missing(tmp_path: Path) -> None:
    target_dir = tmp_path / "inbox"
    assert not target_dir.exists()
    upsert_note(_note(), vault_dir=target_dir)
    assert target_dir.is_dir()


def test_upsert_is_idempotent_for_same_note(tmp_path: Path) -> None:
    note = _note()
    upsert_note(note, vault_dir=tmp_path)
    upsert_note(note, vault_dir=tmp_path)
    assert len(list(tmp_path.glob("*.md"))) == 1


def test_upsert_overwrites_content_for_same_id_title(tmp_path: Path) -> None:
    """Mismo (id, title) con body distinto → un solo fichero con el body nuevo."""
    note_id = uuid4()
    v1 = _note(note_id=note_id, title="Mi idea", body="primera version")
    v2_body = "segunda version mucho más detallada"
    v2 = Note(
        id=note_id,
        title="Mi idea",
        body=v2_body,
        tags=["t"],
        source=NoteSource(call_id=uuid4(), timestamp_start=0.0, timestamp_end=1.0),
        content_hash=hashlib.sha256(v2_body.encode("utf-8")).hexdigest(),
        extracted_by="qwen2.5:7b",
        created_at=datetime.now(tz=UTC),
    )
    p1 = upsert_note(v1, vault_dir=tmp_path)
    p2 = upsert_note(v2, vault_dir=tmp_path)
    assert p1 == p2
    files = list(tmp_path.glob("*.md"))
    assert len(files) == 1
    assert v2_body in files[0].read_text(encoding="utf-8")
    assert "primera version" not in files[0].read_text(encoding="utf-8")
