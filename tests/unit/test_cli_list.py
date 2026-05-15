"""Tests para los comandos `enigma list` (T-114)."""

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
import typer
from typer.testing import CliRunner

from enigma.cli import _parse_last_window, app
from enigma.config import settings
from enigma.db import calls as calls_db
from enigma.db.sqlite import get_connection
from enigma.models.call import Call
from enigma.models.note import Note, NoteSource
from enigma.vault.writer import upsert_note

runner = CliRunner()


# ── _parse_last_window ──────────────────────────────────────────────────────


def test_parse_last_window_days() -> None:
    assert _parse_last_window("7d") == timedelta(days=7)


def test_parse_last_window_hours() -> None:
    assert _parse_last_window("24h") == timedelta(hours=24)


def test_parse_last_window_weeks() -> None:
    assert _parse_last_window("2w") == timedelta(weeks=2)


def test_parse_last_window_minutes() -> None:
    assert _parse_last_window("30m") == timedelta(minutes=30)


def test_parse_last_window_rejects_garbage() -> None:
    with pytest.raises(typer.BadParameter):
        _parse_last_window("banana")


def test_parse_last_window_rejects_missing_unit() -> None:
    with pytest.raises(typer.BadParameter):
        _parse_last_window("7")


# ── enigma list calls ───────────────────────────────────────────────────────


def _make_call(title: str = "Brainstorm") -> Call:
    return Call(
        id=uuid4(),
        content_hash="a" * 64,
        title=title,
        audio_path=Path("/tmp/audio.wav"),
        duration_seconds=600.0,
        language="es",
        recorded_at=datetime(2026, 5, 14, 10, 0, tzinfo=UTC),
        ingested_at=datetime.now(tz=UTC),
    )


def test_list_calls_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enigma_data_path", tmp_path)
    result = runner.invoke(app, ["list", "calls"])
    assert result.exit_code == 0
    assert "No hay llamadas" in result.output


def test_list_calls_shows_registered_call(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "enigma_data_path", tmp_path)
    call = _make_call()
    with get_connection() as conn:
        calls_db.insert_call(conn, call)
    result = runner.invoke(app, ["list", "calls"])
    assert result.exit_code == 0
    assert call.id.hex[:8] in result.output


# ── enigma list notes ───────────────────────────────────────────────────────


def _note(title: str = "Idea", body: str = "Cuerpo.", days_ago: int = 0) -> Note:
    return Note(
        id=uuid4(),
        title=title,
        body=body,
        tags=["t"],
        source=NoteSource(call_id=uuid4(), timestamp_start=0.0, timestamp_end=1.0),
        content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        extracted_by="qwen2.5:7b",
        created_at=datetime.now(tz=UTC) - timedelta(days=days_ago),
    )


def test_list_notes_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enigma_vault_path", tmp_path)
    result = runner.invoke(app, ["list", "notes"])
    assert result.exit_code == 0
    assert "No hay notas" in result.output


def test_list_notes_shows_a_note(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enigma_vault_path", tmp_path)
    upsert_note(_note(title="Captacion"), vault_dir=tmp_path / "inbox")
    result = runner.invoke(app, ["list", "notes"])
    assert result.exit_code == 0
    assert "Captacion" in result.output


def test_list_notes_last_filter_excludes_old(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "enigma_vault_path", tmp_path)
    upsert_note(_note(title="Reciente", days_ago=1), vault_dir=tmp_path / "inbox")
    upsert_note(_note(title="Antigua", days_ago=40), vault_dir=tmp_path / "inbox")
    result = runner.invoke(app, ["list", "notes", "--last", "7d"])
    assert result.exit_code == 0
    assert "Reciente" in result.output
    assert "Antigua" not in result.output


def test_list_notes_rejects_invalid_last(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "enigma_vault_path", tmp_path)
    result = runner.invoke(app, ["list", "notes", "--last", "banana"])
    assert result.exit_code != 0
