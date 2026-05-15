"""Tests unitarios para `enigma.extract.extractor` con cliente Ollama mockeado."""

import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import ollama
import pytest

from enigma.extract.chunker import TranscriptChunk
from enigma.extract.extractor import (
    MAX_LLM_RETRIES,
    ExtractionError,
    _build_note_id,
    extract_notes_from_chunk,
    extract_notes_from_transcript,
)
from enigma.models.transcript import Transcript, TranscriptSegment


def _chunk(text: str = "Manuel: hablamos del precio del padel.") -> TranscriptChunk:
    return TranscriptChunk(
        text=text,
        timestamp_start=10.0,
        timestamp_end=42.5,
        segment_start_index=0,
        segment_end_index=2,
        token_count=20,
    )


def _llm_response_for(payload: object) -> dict[str, dict[str, str]]:
    """Imita el shape `{"message": {"content": "<json>"}}` de ollama.chat."""
    return {"message": {"content": json.dumps(payload)}}


def _mock_chat(payload: object) -> MagicMock:
    """Mockea `_client().chat` para que devuelva el `payload` serializado."""
    client_mock = MagicMock()
    client_mock.chat.return_value = _llm_response_for(payload)
    return client_mock


@pytest.fixture
def call_id() -> UUID:
    return uuid4()


# ── extract_notes_from_chunk: caminos felices ──────────────────────────────


def test_extract_returns_validated_notes(call_id: UUID) -> None:
    payload = [
        {
            "title": "Estrategia padel",
            "body": "Los clubs de padel tienen alta densidad.",
            "tags": ["estrategia", "padel"],
            "timestamp_start": 12.0,
            "timestamp_end": 18.4,
            "speakers": ["Manuel"],
        },
    ]
    with patch("enigma.extract.extractor._client", return_value=_mock_chat(payload)):
        notes = extract_notes_from_chunk(_chunk(), call_id=call_id, model="qwen2.5:7b")
    assert len(notes) == 1
    note = notes[0]
    assert note.title == "Estrategia padel"
    assert note.source.timestamp_start == 12.0
    assert note.source.speakers == ["Manuel"]
    assert note.extracted_by == "qwen2.5:7b"
    assert note.status == "draft"
    assert note.content_hash and len(note.content_hash) == 64


def test_extract_handles_empty_array(call_id: UUID) -> None:
    """Cuando el LLM devuelve `[]`, el extractor devuelve lista vacía."""
    with patch("enigma.extract.extractor._client", return_value=_mock_chat([])):
        notes = extract_notes_from_chunk(_chunk(), call_id=call_id)
    assert notes == []


def test_extract_falls_back_to_chunk_timestamps_when_missing(call_id: UUID) -> None:
    """Si el LLM no devuelve timestamps, se usan los del chunk."""
    payload = [{"title": "Idea", "body": "Cuerpo de la idea."}]
    with patch("enigma.extract.extractor._client", return_value=_mock_chat(payload)):
        notes = extract_notes_from_chunk(_chunk(), call_id=call_id)
    assert len(notes) == 1
    assert notes[0].source.timestamp_start == 10.0
    assert notes[0].source.timestamp_end == 42.5


def test_extract_injects_default_tag_when_llm_omits_tags(call_id: UUID) -> None:
    payload = [{"title": "Idea", "body": "Cuerpo."}]
    with patch("enigma.extract.extractor._client", return_value=_mock_chat(payload)):
        notes = extract_notes_from_chunk(_chunk(), call_id=call_id)
    assert notes[0].tags == ["review-needed"]


def test_extract_skips_malformed_entries_but_keeps_valid_ones(call_id: UUID) -> None:
    payload = [
        {"title": "Buena", "body": "Cuerpo valido."},
        "no es un dict",
        {"title": "Sin body"},  # falta body → KeyError → se descarta
        {"title": "Otra", "body": "Otra idea."},
    ]
    with patch("enigma.extract.extractor._client", return_value=_mock_chat(payload)):
        notes = extract_notes_from_chunk(_chunk(), call_id=call_id)
    assert [n.title for n in notes] == ["Buena", "Otra"]


# ── extract_notes_from_chunk: errores y reintentos ─────────────────────────


def test_extract_raises_when_response_is_unrecognized_dict(call_id: UUID) -> None:
    """Un dict que no envuelve un array conocido y no parece nota se rechaza."""
    payload = {"random": "key", "without": "structure"}
    with patch("enigma.extract.extractor._client", return_value=_mock_chat(payload)):
        with pytest.raises(ExtractionError, match="unrecognized"):
            extract_notes_from_chunk(_chunk(), call_id=call_id)


def test_extract_unwraps_dict_wrapped_under_notes_key(call_id: UUID) -> None:
    """LLM devuelve `{"notes": [...]}` → el extractor desenvuelve."""
    payload = {
        "notes": [
            {"title": "Idea A", "body": "Cuerpo A."},
            {"title": "Idea B", "body": "Cuerpo B."},
        ],
    }
    with patch("enigma.extract.extractor._client", return_value=_mock_chat(payload)):
        notes = extract_notes_from_chunk(_chunk(), call_id=call_id)
    assert [n.title for n in notes] == ["Idea A", "Idea B"]


def test_extract_unwraps_dict_wrapped_under_alternate_keys(call_id: UUID) -> None:
    """Acepta keys alternativas comunes: `ideas`, `results`, etc."""
    payload = {"ideas": [{"title": "Una", "body": "Cuerpo una."}]}
    with patch("enigma.extract.extractor._client", return_value=_mock_chat(payload)):
        notes = extract_notes_from_chunk(_chunk(), call_id=call_id)
    assert len(notes) == 1
    assert notes[0].title == "Una"


def test_extract_wraps_single_note_dict_into_list(call_id: UUID) -> None:
    """Si el LLM olvida el array y devuelve un solo objeto nota, lo aceptamos."""
    payload = {"title": "Sola", "body": "Una sola nota directa."}
    with patch("enigma.extract.extractor._client", return_value=_mock_chat(payload)):
        notes = extract_notes_from_chunk(_chunk(), call_id=call_id)
    assert len(notes) == 1
    assert notes[0].title == "Sola"


def test_extract_retries_on_invalid_json_then_succeeds(call_id: UUID) -> None:
    """Primera respuesta inválida, segunda OK → devuelve notas."""
    bad_response = {"message": {"content": "{not valid json"}}
    good_response = _llm_response_for([{"title": "OK", "body": "Cuerpo OK."}])

    client_mock = MagicMock()
    client_mock.chat.side_effect = [bad_response, good_response]
    with patch("enigma.extract.extractor._client", return_value=client_mock):
        notes = extract_notes_from_chunk(_chunk(), call_id=call_id)
    assert client_mock.chat.call_count == 2
    assert len(notes) == 1


def test_extract_raises_after_max_retries(call_id: UUID) -> None:
    bad_response = {"message": {"content": "{still broken"}}
    client_mock = MagicMock()
    client_mock.chat.return_value = bad_response
    with patch("enigma.extract.extractor._client", return_value=client_mock):
        with pytest.raises(ExtractionError):
            extract_notes_from_chunk(_chunk(), call_id=call_id)
    assert client_mock.chat.call_count == MAX_LLM_RETRIES


def test_extract_retries_on_ollama_response_error(call_id: UUID) -> None:
    """Una excepción `ollama.ResponseError` se considera reintentable."""
    good_response = _llm_response_for([{"title": "OK", "body": "Cuerpo OK."}])
    client_mock = MagicMock()
    client_mock.chat.side_effect = [
        ollama.ResponseError("upstream blip"),
        good_response,
    ]
    with patch("enigma.extract.extractor._client", return_value=client_mock):
        notes = extract_notes_from_chunk(_chunk(), call_id=call_id)
    assert len(notes) == 1


# ── note_id determinismo ───────────────────────────────────────────────────


def test_note_id_is_deterministic_for_same_seed(call_id: UUID) -> None:
    a = _build_note_id(call_id, 0, "Estrategia padel")
    b = _build_note_id(call_id, 0, "Estrategia padel")
    assert a == b


def test_note_id_changes_when_seed_changes(call_id: UUID) -> None:
    a = _build_note_id(call_id, 0, "Estrategia padel")
    b = _build_note_id(call_id, 1, "Estrategia padel")
    c = _build_note_id(call_id, 0, "Otra idea")
    assert len({a, b, c}) == 3


# ── extract_notes_from_transcript: orquestación ────────────────────────────


def test_extract_from_transcript_aggregates_chunks() -> None:
    transcript = Transcript(
        call_id=uuid4(),
        model="faster-whisper:tiny",
        created_at=datetime.now(tz=UTC),
        segments=[
            TranscriptSegment(start=0.0, end=1.0, text="primer segmento"),
            TranscriptSegment(start=1.0, end=2.0, text="segundo segmento"),
        ],
    )
    payload = [{"title": "T1", "body": "Cuerpo uno."}]
    with patch("enigma.extract.extractor._client", return_value=_mock_chat(payload)):
        notes = extract_notes_from_transcript(transcript)
    assert len(notes) >= 1
    assert all(n.source.call_id == transcript.call_id for n in notes)


def test_extract_from_empty_transcript_returns_empty_list() -> None:
    transcript = Transcript(
        call_id=uuid4(),
        model="faster-whisper:tiny",
        created_at=datetime.now(tz=UTC),
        segments=[],
    )
    # Con 0 chunks, ni siquiera tocamos el cliente.
    client_mock = MagicMock()
    with patch("enigma.extract.extractor._client", return_value=client_mock):
        notes = extract_notes_from_transcript(transcript)
    assert notes == []
    client_mock.chat.assert_not_called()
