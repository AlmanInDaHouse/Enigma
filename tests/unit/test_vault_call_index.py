"""Tests para la nota índice de llamada (T-112)."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import frontmatter as fm
import pytest

from enigma.config import settings
from enigma.models.call import Call
from enigma.models.note import Note, NoteSource
from enigma.vault.writer import (
    call_index_filename,
    note_filename,
    render_call_index_markdown,
    write_call_index,
)

_FIXED_DATE = datetime(2026, 5, 14, 18, 32, tzinfo=UTC)


def _call(
    *,
    call_id: UUID | None = None,
    title: str | None = "Brainstorm captación padel",
    recorded_at: datetime = _FIXED_DATE,
    duration: float = 2832.5,
    participants: list[str] | None = None,
) -> Call:
    return Call(
        id=call_id if call_id is not None else uuid4(),
        content_hash="a" * 64,
        title=title,
        audio_path=Path("/tmp/audio.wav"),
        duration_seconds=duration,
        language="es",
        recorded_at=recorded_at,
        ingested_at=datetime.now(tz=UTC),
        participants=participants if participants is not None else ["Manuel"],
    )


def _note(title: str = "Estrategia padel", body: str = "Cuerpo.") -> Note:
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


# ── call_index_filename ─────────────────────────────────────────────────────


def test_filename_combines_date_slug_and_short_id() -> None:
    call_id = UUID("3b9f7a2c-aaaa-4bbb-8ccc-ddddeeeeffff")
    call = _call(call_id=call_id, title="Brainstorm captación padel")
    name = call_index_filename(call)
    assert name.startswith("2026-05-14-brainstorm-captacion-padel-")
    assert name.endswith(".md")
    assert call_id.hex[:8] in name


def test_filename_falls_back_to_llamada_when_title_missing() -> None:
    name = call_index_filename(_call(title=None))
    assert "-llamada-" in name


def test_filename_falls_back_to_llamada_when_title_only_punctuation() -> None:
    name = call_index_filename(_call(title="...!!!"))
    assert "-llamada-" in name


def test_filename_is_deterministic_for_same_call() -> None:
    call = _call()
    assert call_index_filename(call) == call_index_filename(call)


def test_two_calls_same_day_same_title_differ_by_short_id() -> None:
    a = _call(call_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"), title="Misma cosa")
    b = _call(call_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"), title="Misma cosa")
    assert call_index_filename(a) != call_index_filename(b)


# ── render_call_index_markdown ──────────────────────────────────────────────


def test_markdown_starts_with_frontmatter() -> None:
    md = render_call_index_markdown(_call(), [])
    assert md.startswith("---\n")
    assert "\n---\n\n# " in md


def test_markdown_frontmatter_has_required_fields() -> None:
    md = render_call_index_markdown(_call(), [])
    meta = fm.loads(md).metadata
    for key in (
        "type",
        "call_id",
        "recorded_at",
        "duration_seconds",
        "language",
        "participants",
        "status",
        "note_count",
    ):
        assert key in meta
    assert meta["type"] == "call"


def test_markdown_note_count_matches_notes_length() -> None:
    notes = [_note(title=f"Idea {i}") for i in range(3)]
    md = render_call_index_markdown(_call(), notes)
    meta = fm.loads(md).metadata
    assert meta["note_count"] == 3


def test_markdown_lists_each_note_as_wikilink() -> None:
    notes = [_note(title="Idea uno"), _note(title="Idea dos")]
    md = render_call_index_markdown(_call(), notes)
    for note in notes:
        slug = note_filename(note)[:-3]  # quita `.md`
        assert f"[[{slug}]]" in md


def test_markdown_shows_message_when_no_notes() -> None:
    md = render_call_index_markdown(_call(), [])
    assert "No se extrajeron notas" in md


def test_markdown_header_uses_date_and_title() -> None:
    md = render_call_index_markdown(_call(title="Brainstorm captación padel"), [])
    assert "# 2026-05-14 — Brainstorm captación padel" in md


def test_markdown_header_handles_missing_title() -> None:
    md = render_call_index_markdown(_call(title=None), [])
    assert "Llamada sin título" in md


def test_markdown_includes_duration_in_minutes() -> None:
    md = render_call_index_markdown(_call(duration=2832.5), [])
    assert "47.2 min" in md or "47.3 min" in md


# ── write_call_index ────────────────────────────────────────────────────────


def test_write_creates_calls_dir(tmp_path: Path) -> None:
    assert not (tmp_path / "calls").exists()
    write_call_index(_call(), [_note()], vault_path=tmp_path)
    assert (tmp_path / "calls").is_dir()


def test_write_returns_path_under_calls(tmp_path: Path) -> None:
    path = write_call_index(_call(), [], vault_path=tmp_path)
    assert path.parent == tmp_path / "calls"
    assert path.name.endswith(".md")


def test_write_is_idempotent(tmp_path: Path) -> None:
    call = _call()
    write_call_index(call, [_note()], vault_path=tmp_path)
    write_call_index(call, [_note(), _note()], vault_path=tmp_path)
    files = list((tmp_path / "calls").glob("*.md"))
    assert len(files) == 1


def test_write_uses_settings_vault_when_no_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "enigma_vault_path", tmp_path)
    path = write_call_index(
        _call(),
        [],
    )
    assert path.parent == tmp_path / "calls"


def test_write_content_contains_each_note_wikilink(tmp_path: Path) -> None:
    notes = [_note(title="Una"), _note(title="Otra")]
    path = write_call_index(_call(), notes, vault_path=tmp_path)
    content = path.read_text(encoding="utf-8")
    for n in notes:
        slug = note_filename(n)[:-3]
        assert f"[[{slug}]]" in content
