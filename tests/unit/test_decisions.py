"""Tests unitarios para `enigma.agent.decisions` (T-402).

Mockean `get_connection`, `calls_db.list_calls`, `load_transcript` y el
cliente Ollama para verificar la extracción y el render sin tocar SQLite, el
disco de transcripts ni el LLM real.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

from enigma.agent.decisions import (
    Decision,
    DecisionsError,
    build_decision_index,
    extract_decisions_from_call,
    render_decisions_markdown,
)
from enigma.models.call import Call
from enigma.models.transcript import Transcript, TranscriptSegment


def _call(title: str = "Brainstorm", *, recorded: datetime | None = None) -> Call:
    return Call(
        id=uuid4(),
        content_hash=uuid4().hex + uuid4().hex,
        title=title,
        audio_path=Path("/tmp/audio.wav"),
        duration_seconds=600.0,
        language="es",
        recorded_at=recorded or datetime(2026, 5, 14, 10, 0, tzinfo=UTC),
        ingested_at=datetime.now(tz=UTC),
    )


def _transcript(call_id: object, *, empty: bool = False) -> Transcript:
    segments = (
        []
        if empty
        else [TranscriptSegment(start=0.0, end=5.0, text="Decidimos lanzar la campaña.")]
    )
    return Transcript(
        call_id=call_id,  # type: ignore[arg-type]
        model="faster-whisper:large-v3",
        language="es",
        segments=segments,
        created_at=datetime.now(tz=UTC),
    )


def _llm_client(decisions: list[str]) -> MagicMock:
    """Cliente Ollama falso cuyo `.chat` devuelve `{"decisions": [...]}`."""
    client = MagicMock()
    client.chat.return_value = {"message": {"content": json.dumps({"decisions": decisions})}}
    return client


def _decision(statement: str, *, recorded: datetime, title: str = "Llamada") -> Decision:
    return Decision(
        statement=statement,
        call_id=uuid4(),
        call_title=title,
        recorded_at=recorded,
        call_index_stem=f"{recorded:%Y-%m-%d}-llamada-abcdef12",
    )


# ── extract_decisions_from_call ─────────────────────────────────────────────


def test_extract_maps_statements_to_decisions() -> None:
    call = _call()
    with patch(
        "enigma.agent.decisions._client",
        return_value=_llm_client(["Lanzar campaña", "Subir precios"]),
    ):
        decisions = extract_decisions_from_call(call, _transcript(call.id))
    assert [d.statement for d in decisions] == ["Lanzar campaña", "Subir precios"]
    assert all(d.call_id == call.id for d in decisions)
    assert all(d.recorded_at == call.recorded_at for d in decisions)


def test_extract_empty_transcript_skips_llm() -> None:
    call = _call()
    client = _llm_client(["no debería llamarse"])
    with patch("enigma.agent.decisions._client", return_value=client):
        decisions = extract_decisions_from_call(call, _transcript(call.id, empty=True))
    assert decisions == []
    client.chat.assert_not_called()


def test_extract_drops_blank_statements() -> None:
    call = _call()
    with patch(
        "enigma.agent.decisions._client",
        return_value=_llm_client(["Decisión real", "   "]),
    ):
        decisions = extract_decisions_from_call(call, _transcript(call.id))
    assert len(decisions) == 1


# ── render_decisions_markdown ───────────────────────────────────────────────


def test_render_groups_and_orders_reverse_chronologically() -> None:
    old = _decision("Vieja", recorded=datetime(2026, 1, 1, tzinfo=UTC))
    recent = _decision("Reciente", recorded=datetime(2026, 5, 1, tzinfo=UTC))
    md = render_decisions_markdown([old, recent])
    assert md.index("Reciente") < md.index("Vieja")
    assert "type: decision-index" in md
    assert "decision_count: 2" in md


def test_render_links_to_call_index() -> None:
    decision = _decision("Algo", recorded=datetime(2026, 5, 1, tzinfo=UTC), title="Sprint")
    md = render_decisions_markdown([decision])
    assert "[[2026-05-01-llamada-abcdef12|Sprint]]" in md


def test_render_empty_corpus() -> None:
    md = render_decisions_markdown([])
    assert "type: decision-index" in md
    assert "decision_count: 0" in md
    assert "No se ha registrado ninguna decisión" in md


# ── build_decision_index ────────────────────────────────────────────────────


def test_build_index_aggregates_corpus(tmp_path: Path) -> None:
    call_a = _call("Llamada A", recorded=datetime(2026, 5, 1, 9, 0, tzinfo=UTC))
    call_b = _call("Llamada B", recorded=datetime(2026, 5, 2, 9, 0, tzinfo=UTC))
    transcripts = {call_a.id: _transcript(call_a.id), call_b.id: _transcript(call_b.id)}

    with (
        patch("enigma.agent.decisions.get_connection"),
        patch("enigma.agent.decisions.calls_db.list_calls", return_value=[call_a, call_b]),
        patch(
            "enigma.agent.decisions.load_transcript", side_effect=lambda cid: transcripts.get(cid)
        ),
        patch("enigma.agent.decisions._client", return_value=_llm_client(["Una decisión"])),
    ):
        result = build_decision_index(vault_path=tmp_path)

    assert result.calls_scanned == 2
    assert result.calls_with_decisions == 2
    assert len(result.decisions) == 2
    assert result.index_path == tmp_path / "decisions.md"
    assert result.index_path.exists()


def test_build_index_skips_calls_without_transcript(tmp_path: Path) -> None:
    call_a = _call("Con transcript")
    call_b = _call("Sin transcript")
    with (
        patch("enigma.agent.decisions.get_connection"),
        patch("enigma.agent.decisions.calls_db.list_calls", return_value=[call_a, call_b]),
        patch(
            "enigma.agent.decisions.load_transcript",
            side_effect=lambda cid: _transcript(cid) if cid == call_a.id else None,
        ),
        patch("enigma.agent.decisions._client", return_value=_llm_client(["D"])),
    ):
        result = build_decision_index(vault_path=tmp_path)
    assert result.calls_scanned == 1


def test_build_index_continues_when_a_call_fails(tmp_path: Path) -> None:
    """Si la extracción de una llamada falla, el índice se construye igual."""
    call_ok = _call("OK")
    call_bad = _call("Falla")
    with (
        patch("enigma.agent.decisions.get_connection"),
        patch("enigma.agent.decisions.calls_db.list_calls", return_value=[call_ok, call_bad]),
        patch("enigma.agent.decisions.load_transcript", side_effect=_transcript),
        patch(
            "enigma.agent.decisions.extract_decisions_from_call",
            side_effect=[
                [_decision("Decisión válida", recorded=call_ok.recorded_at)],
                DecisionsError("boom"),
            ],
        ),
    ):
        result = build_decision_index(vault_path=tmp_path)
    assert result.calls_scanned == 2
    assert len(result.decisions) == 1
    assert result.index_path.exists()


def test_build_index_empty_corpus_writes_empty_index(tmp_path: Path) -> None:
    with (
        patch("enigma.agent.decisions.get_connection"),
        patch("enigma.agent.decisions.calls_db.list_calls", return_value=[]),
    ):
        result = build_decision_index(vault_path=tmp_path)
    assert result.decisions == []
    assert result.index_path.exists()
    assert "decision_count: 0" in result.index_path.read_text(encoding="utf-8")
