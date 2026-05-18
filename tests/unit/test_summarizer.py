"""Tests unitarios para `enigma.agent.summarizer` (T-401).

Mockean `get_connection`, `calls_db.get_call`, `load_transcript` y el cliente
Ollama para verificar el flujo sin tocar SQLite, el disco de transcripts ni
el LLM real.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from enigma.agent.summarizer import (
    CallSummary,
    SummarizationError,
    read_call_summary,
    render_summary_markdown,
    summarize_call,
    write_call_summary,
)
from enigma.models.call import Call
from enigma.models.transcript import Transcript, TranscriptSegment


def _call(title: str = "Brainstorm pádel") -> Call:
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


def _transcript(call_id: object, *, empty: bool = False) -> Transcript:
    segments = (
        []
        if empty
        else [
            TranscriptSegment(
                start=0.0, end=5.0, text="Hablamos de captar socios.", speaker="SPEAKER_00"
            ),
            TranscriptSegment(
                start=5.0, end=9.0, text="Y de subir el ticket medio.", speaker="SPEAKER_01"
            ),
        ]
    )
    return Transcript(
        call_id=call_id,  # type: ignore[arg-type]
        model="faster-whisper:large-v3",
        language="es",
        segments=segments,
        created_at=datetime.now(tz=UTC),
    )


def _summary() -> CallSummary:
    return CallSummary(
        tldr="El equipo definió la estrategia de captación.",
        key_points=["Captar socios por densidad de clubs", "Subir el ticket medio"],
        topics=["captación", "pricing"],
    )


def _llm_client(summary: CallSummary) -> MagicMock:
    """Cliente Ollama falso cuyo `.chat` devuelve el `summary` serializado."""
    client = MagicMock()
    client.chat.return_value = {"message": {"content": summary.model_dump_json()}}
    return client


# ── render_summary_markdown ─────────────────────────────────────────────────


def test_render_has_frontmatter_and_sections() -> None:
    md = render_summary_markdown(_call(), _summary())
    assert md.startswith("---\n")
    assert "type: call-summary" in md
    assert "# Resumen ejecutivo" in md
    assert "## TL;DR" in md
    assert "## Puntos clave" in md
    assert "## Temas tratados" in md
    assert "Captar socios por densidad de clubs" in md


def test_render_links_back_to_call_index() -> None:
    md = render_summary_markdown(_call(), _summary())
    assert "> Llamada: [[2026-05-14-" in md


def test_render_handles_empty_lists() -> None:
    md = render_summary_markdown(
        _call(),
        CallSummary(tldr="Poca cosa.", key_points=[], topics=[]),
    )
    assert "_Sin puntos clave identificados._" in md
    assert "_Sin temas identificados._" in md


# ── read_call_summary (T-703) ───────────────────────────────────────────────


def test_read_call_summary_round_trips_what_was_written(tmp_path: Path) -> None:
    """`read_call_summary` recupera el `CallSummary` que escribió `write_call_summary`."""
    call = _call()
    original = _summary()
    write_call_summary(call, original, vault_path=tmp_path)
    recovered = read_call_summary(call, vault_path=tmp_path)
    assert recovered == original


def test_read_call_summary_handles_empty_lists(tmp_path: Path) -> None:
    """Los placeholders `_Sin..._` se leen como listas vacías, no como un item."""
    call = _call()
    write_call_summary(
        call,
        CallSummary(tldr="Poca cosa.", key_points=[], topics=[]),
        vault_path=tmp_path,
    )
    recovered = read_call_summary(call, vault_path=tmp_path)
    assert recovered is not None
    assert recovered.tldr == "Poca cosa."
    assert recovered.key_points == []
    assert recovered.topics == []


def test_read_call_summary_none_when_file_absent(tmp_path: Path) -> None:
    assert read_call_summary(_call(), vault_path=tmp_path) is None


# ── summarize_call ──────────────────────────────────────────────────────────


def test_summarize_call_writes_note(tmp_path: Path) -> None:
    call = _call()
    with (
        patch("enigma.agent.summarizer.get_connection"),
        patch("enigma.agent.summarizer.calls_db.get_call", return_value=call),
        patch("enigma.agent.summarizer.load_transcript", return_value=_transcript(call.id)),
        patch("enigma.agent.summarizer._client", return_value=_llm_client(_summary())),
    ):
        result = summarize_call(call.id, vault_path=tmp_path)
    assert result.summary_path.exists()
    assert result.summary_path.parent == tmp_path / "calls"
    assert result.summary.tldr == "El equipo definió la estrategia de captación."
    assert "type: call-summary" in result.summary_path.read_text(encoding="utf-8")


def test_summarize_call_is_idempotent(tmp_path: Path) -> None:
    call = _call()
    with (
        patch("enigma.agent.summarizer.get_connection"),
        patch("enigma.agent.summarizer.calls_db.get_call", return_value=call),
        patch("enigma.agent.summarizer.load_transcript", return_value=_transcript(call.id)),
        patch("enigma.agent.summarizer._client", return_value=_llm_client(_summary())),
    ):
        summarize_call(call.id, vault_path=tmp_path)
        summarize_call(call.id, vault_path=tmp_path)
    assert len(list((tmp_path / "calls").glob("*.md"))) == 1


def test_summarize_unknown_call_raises(tmp_path: Path) -> None:
    with (
        patch("enigma.agent.summarizer.get_connection"),
        patch("enigma.agent.summarizer.calls_db.get_call", return_value=None),
        pytest.raises(SummarizationError, match="No existe"),
    ):
        summarize_call(uuid4(), vault_path=tmp_path)


def test_summarize_without_transcript_raises(tmp_path: Path) -> None:
    call = _call()
    with (
        patch("enigma.agent.summarizer.get_connection"),
        patch("enigma.agent.summarizer.calls_db.get_call", return_value=call),
        patch("enigma.agent.summarizer.load_transcript", return_value=None),
        pytest.raises(SummarizationError, match="transcripción persistida"),
    ):
        summarize_call(call.id, vault_path=tmp_path)


def test_summarize_empty_transcript_raises(tmp_path: Path) -> None:
    call = _call()
    with (
        patch("enigma.agent.summarizer.get_connection"),
        patch("enigma.agent.summarizer.calls_db.get_call", return_value=call),
        patch(
            "enigma.agent.summarizer.load_transcript",
            return_value=_transcript(call.id, empty=True),
        ),
        pytest.raises(SummarizationError, match="vacía"),
    ):
        summarize_call(call.id, vault_path=tmp_path)


def test_summarize_llm_bad_json_raises(tmp_path: Path) -> None:
    call = _call()
    bad_client = MagicMock()
    bad_client.chat.return_value = {"message": {"content": "{no es json"}}
    with (
        patch("enigma.agent.summarizer.get_connection"),
        patch("enigma.agent.summarizer.calls_db.get_call", return_value=call),
        patch("enigma.agent.summarizer.load_transcript", return_value=_transcript(call.id)),
        patch("enigma.agent.summarizer._client", return_value=bad_client),
        pytest.raises(SummarizationError, match="no produjo un resumen válido"),
    ):
        summarize_call(call.id, vault_path=tmp_path)


def test_summarize_llm_missing_field_raises(tmp_path: Path) -> None:
    """JSON sintácticamente válido pero sin los campos requeridos → error."""
    call = _call()
    incomplete = MagicMock()
    incomplete.chat.return_value = {"message": {"content": json.dumps({"tldr": "solo esto"})}}
    with (
        patch("enigma.agent.summarizer.get_connection"),
        patch("enigma.agent.summarizer.calls_db.get_call", return_value=call),
        patch("enigma.agent.summarizer.load_transcript", return_value=_transcript(call.id)),
        patch("enigma.agent.summarizer._client", return_value=incomplete),
        pytest.raises(SummarizationError),
    ):
        summarize_call(call.id, vault_path=tmp_path)
