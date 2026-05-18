"""Tests unitarios para `enigma.agent.brainstorm` (T-704).

Mockean `get_connection`, `calls_db.get_call`, `load_transcript` y el cliente
Ollama para verificar `brainstorm_call` sin tocar la BD ni el LLM reales.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from enigma.agent.brainstorm import (
    Brainstorm,
    BrainstormError,
    brainstorm_call,
)
from enigma.agent.prompts import build_brainstorm_messages
from enigma.models.call import Call
from enigma.models.transcript import Transcript, TranscriptSegment


def _call(title: str = "Estrategia de captación") -> Call:
    return Call(
        id=uuid4(),
        content_hash="b" * 64,
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


def _payload(
    *,
    analogies: list[str] | None = None,
    next_steps: list[str] | None = None,
    open_questions: list[str] | None = None,
    risks: list[str] | None = None,
) -> str:
    """Serializa un payload de brainstorming como lo devolvería el LLM."""
    return json.dumps(
        {
            "analogies": analogies if analogies is not None else ["Como un gimnasio"],
            "next_steps": next_steps if next_steps is not None else ["Pilotar con un club"],
            "open_questions": (
                open_questions if open_questions is not None else ["¿Qué densidad mínima?"]
            ),
            "risks": risks if risks is not None else ["Canibalizar socios actuales"],
        }
    )


def _llm_client(content: str) -> MagicMock:
    """Cliente Ollama falso cuyo `.chat` devuelve `content` como respuesta."""
    client = MagicMock()
    client.chat.return_value = {"message": {"content": content}}
    return client


# ── brainstorm_call ─────────────────────────────────────────────────────────


def test_brainstorm_call_returns_expanded_ideas() -> None:
    call = _call()
    with (
        patch("enigma.agent.brainstorm.get_connection"),
        patch("enigma.agent.brainstorm.calls_db.get_call", return_value=call),
        patch("enigma.agent.brainstorm.load_transcript", return_value=_transcript(call.id)),
        patch("enigma.agent.brainstorm._client", return_value=_llm_client(_payload())),
    ):
        result = brainstorm_call(call.id)
    assert isinstance(result, Brainstorm)
    assert result.call_id == call.id
    assert result.analogies == ["Como un gimnasio"]
    assert result.next_steps == ["Pilotar con un club"]
    assert result.open_questions == ["¿Qué densidad mínima?"]
    assert result.risks == ["Canibalizar socios actuales"]


def test_brainstorm_call_strips_blank_items() -> None:
    """Los items en blanco que cuele el LLM se descartan."""
    call = _call()
    payload = _payload(analogies=["Idea válida", "   ", ""])
    with (
        patch("enigma.agent.brainstorm.get_connection"),
        patch("enigma.agent.brainstorm.calls_db.get_call", return_value=call),
        patch("enigma.agent.brainstorm.load_transcript", return_value=_transcript(call.id)),
        patch("enigma.agent.brainstorm._client", return_value=_llm_client(payload)),
    ):
        result = brainstorm_call(call.id)
    assert result.analogies == ["Idea válida"]


def test_brainstorm_call_accepts_empty_categories() -> None:
    """Una categoría sin ideas (`[]`) es válida, no un error."""
    call = _call()
    payload = _payload(risks=[])
    with (
        patch("enigma.agent.brainstorm.get_connection"),
        patch("enigma.agent.brainstorm.calls_db.get_call", return_value=call),
        patch("enigma.agent.brainstorm.load_transcript", return_value=_transcript(call.id)),
        patch("enigma.agent.brainstorm._client", return_value=_llm_client(payload)),
    ):
        result = brainstorm_call(call.id)
    assert result.risks == []


def test_brainstorm_unknown_call_raises() -> None:
    with (
        patch("enigma.agent.brainstorm.get_connection"),
        patch("enigma.agent.brainstorm.calls_db.get_call", return_value=None),
        pytest.raises(BrainstormError, match="No existe"),
    ):
        brainstorm_call(uuid4())


def test_brainstorm_without_transcript_raises() -> None:
    call = _call()
    with (
        patch("enigma.agent.brainstorm.get_connection"),
        patch("enigma.agent.brainstorm.calls_db.get_call", return_value=call),
        patch("enigma.agent.brainstorm.load_transcript", return_value=None),
        pytest.raises(BrainstormError, match="transcripción"),
    ):
        brainstorm_call(call.id)


def test_brainstorm_empty_transcript_raises() -> None:
    call = _call()
    with (
        patch("enigma.agent.brainstorm.get_connection"),
        patch("enigma.agent.brainstorm.calls_db.get_call", return_value=call),
        patch(
            "enigma.agent.brainstorm.load_transcript",
            return_value=_transcript(call.id, empty=True),
        ),
        pytest.raises(BrainstormError, match="vacía"),
    ):
        brainstorm_call(call.id)


def test_brainstorm_invalid_json_raises_after_retries() -> None:
    call = _call()
    with (
        patch("enigma.agent.brainstorm.get_connection"),
        patch("enigma.agent.brainstorm.calls_db.get_call", return_value=call),
        patch("enigma.agent.brainstorm.load_transcript", return_value=_transcript(call.id)),
        patch("enigma.agent.brainstorm._client", return_value=_llm_client("no es json")),
        pytest.raises(BrainstormError, match="válido"),
    ):
        brainstorm_call(call.id)


# ── build_brainstorm_messages ───────────────────────────────────────────────


def test_build_brainstorm_messages_has_system_and_user() -> None:
    messages = build_brainstorm_messages(
        "Transcripción de prueba.", call_title="Daily", language="es"
    )
    assert [m["role"] for m in messages] == ["system", "user"]
    assert "Daily" in messages[1]["content"]
    assert "Transcripción de prueba." in messages[1]["content"]
