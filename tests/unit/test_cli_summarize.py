"""Tests para el comando `enigma summarize call` (T-401).

Usan una SQLite temporal con Calls reales para ejercitar la resolución de
id/prefijo, y mockean `summarize_call` (el paso costoso).
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from typer.testing import CliRunner

from enigma.agent.summarizer import CallSummary, SummarizationError, SummaryResult
from enigma.cli import app
from enigma.config import settings
from enigma.db import calls as calls_db
from enigma.db.sqlite import get_connection
from enigma.models.call import Call

runner = CliRunner()


def _make_call(
    call_id: UUID | None = None,
    *,
    title: str = "Brainstorm",
    content_hash: str | None = None,
) -> Call:
    return Call(
        id=call_id if call_id is not None else uuid4(),
        content_hash=content_hash or (uuid4().hex + uuid4().hex),
        title=title,
        audio_path=Path("/tmp/audio.wav"),
        duration_seconds=600.0,
        language="es",
        recorded_at=datetime(2026, 5, 14, 10, 0, tzinfo=UTC),
        ingested_at=datetime.now(tz=UTC),
    )


def _insert(call: Call) -> None:
    with get_connection() as conn:
        calls_db.insert_call(conn, call)


def _result(call: Call) -> SummaryResult:
    return SummaryResult(
        call=call,
        summary=CallSummary(tldr="Resumen breve.", key_points=["a", "b"], topics=["t"]),
        summary_path=Path("/vault/calls/2026-05-14-brainstorm-summary.md"),
    )


def test_summarize_call_resolves_short_prefix(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "enigma_data_path", tmp_path)
    call = _make_call()
    _insert(call)
    with patch("enigma.agent.summarizer.summarize_call", return_value=_result(call)) as mock:
        result = runner.invoke(app, ["summarize", "call", call.id.hex[:8]])
    assert result.exit_code == 0
    assert mock.call_args.args[0] == call.id
    assert "generado" in result.output


def test_summarize_call_accepts_full_uuid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "enigma_data_path", tmp_path)
    call = _make_call()
    _insert(call)
    with patch("enigma.agent.summarizer.summarize_call", return_value=_result(call)) as mock:
        result = runner.invoke(app, ["summarize", "call", str(call.id)])
    assert result.exit_code == 0
    assert mock.call_args.args[0] == call.id


def test_summarize_call_unknown_id_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "enigma_data_path", tmp_path)
    _insert(_make_call())
    result = runner.invoke(app, ["summarize", "call", "deadbeef"])
    assert result.exit_code != 0


def test_summarize_call_ambiguous_prefix_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "enigma_data_path", tmp_path)
    # Dos calls cuyo id comparte el prefijo "0000...".
    shared = "00000000"
    _insert(_make_call(UUID(hex=shared + "0" * 24)))
    _insert(_make_call(UUID(hex=shared + "1" * 24)))
    result = runner.invoke(app, ["summarize", "call", shared])
    assert result.exit_code != 0
    assert "ambiguo" in result.output


def test_summarize_call_propagates_summarization_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "enigma_data_path", tmp_path)
    call = _make_call()
    _insert(call)
    with patch(
        "enigma.agent.summarizer.summarize_call",
        side_effect=SummarizationError("transcript ausente"),
    ):
        result = runner.invoke(app, ["summarize", "call", call.id.hex[:8]])
    assert result.exit_code == 1
    assert "Error" in result.output
