"""Tests unitarios para `enigma.pipeline.ingest_audio` (T-113).

Mockea cada dependencia (register_call, transcribe, save_transcript,
extract_notes_from_transcript, write_notes_to_inbox, write_call_index,
_update_status) para verificar la **orquestación**, no la lógica interna
de cada paso.
"""

import hashlib
from collections.abc import Generator
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

from enigma.models.call import Call
from enigma.models.note import Note, NoteSource
from enigma.models.transcript import Transcript
from enigma.pipeline import IngestResult, ingest_audio


def _call(title: str | None = "Brainstorm padel") -> Call:
    return Call(
        id=uuid4(),
        content_hash="a" * 64,
        title=title,
        audio_path=Path("/tmp/audio.wav"),
        duration_seconds=120.0,
        language="es",
        recorded_at=datetime.now(tz=UTC),
        ingested_at=datetime.now(tz=UTC),
    )


def _transcript(call_id: object) -> Transcript:
    return Transcript(
        call_id=call_id,  # type: ignore[arg-type]
        model="faster-whisper:tiny",
        created_at=datetime.now(tz=UTC),
    )


def _note() -> Note:
    body = "Cuerpo único."
    return Note(
        id=uuid4(),
        title="Idea",
        body=body,
        tags=["t"],
        source=NoteSource(call_id=uuid4(), timestamp_start=0.0, timestamp_end=1.0),
        content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        extracted_by="qwen2.5:7b",
        created_at=datetime.now(tz=UTC),
    )


@contextmanager
def _patched_pipeline(call: Call) -> Generator[dict[str, MagicMock]]:
    """Patchea todas las deps de `pipeline` y entrega los mocks por nombre."""
    notes = [_note(), _note()]
    note_paths = [Path("/tmp/inbox/a.md"), Path("/tmp/inbox/b.md")]
    transcript_path = Path("/tmp/transcripts/x.json")
    call_index_path = Path("/tmp/calls/y.md")

    mocks: dict[str, MagicMock] = {
        "register": MagicMock(return_value=call),
        "transcribe": MagicMock(return_value=_transcript(call.id)),
        "save": MagicMock(return_value=transcript_path),
        "extract": MagicMock(return_value=notes),
        "write_notes": MagicMock(return_value=note_paths),
        "write_index": MagicMock(return_value=call_index_path),
        "update_status": MagicMock(),
    }
    targets = {
        "register": "enigma.pipeline.register_call",
        "transcribe": "enigma.pipeline.transcribe",
        "save": "enigma.pipeline.save_transcript",
        "extract": "enigma.pipeline.extract_notes_from_transcript",
        "write_notes": "enigma.pipeline.write_notes_to_inbox",
        "write_index": "enigma.pipeline.write_call_index",
        "update_status": "enigma.pipeline._update_status",
    }
    with ExitStack() as stack:
        for name, target in targets.items():
            stack.enter_context(patch(target, mocks[name]))
        yield mocks


# ── Orquestación ────────────────────────────────────────────────────────────


def test_ingest_audio_calls_each_step_once() -> None:
    call = _call()
    with _patched_pipeline(call) as mocks:
        ingest_audio(Path("/tmp/audio.wav"))
    assert mocks["register"].call_count == 1
    assert mocks["transcribe"].call_count == 1
    assert mocks["save"].call_count == 1
    assert mocks["extract"].call_count == 1
    assert mocks["write_notes"].call_count == 1
    assert mocks["write_index"].call_count == 1


def test_ingest_audio_passes_title_to_register() -> None:
    call = _call()
    with _patched_pipeline(call) as mocks:
        ingest_audio(Path("/tmp/audio.wav"), title="Reunión equipo")
    assert mocks["register"].call_args.kwargs["title"] == "Reunión equipo"


def test_ingest_audio_returns_ingest_result_with_all_paths() -> None:
    call = _call()
    with _patched_pipeline(call):
        result = ingest_audio(Path("/tmp/audio.wav"))
    assert isinstance(result, IngestResult)
    assert result.call.status == "done"
    assert result.transcript_path == Path("/tmp/transcripts/x.json")
    assert len(result.note_paths) == 2
    assert result.call_index_path == Path("/tmp/calls/y.md")


def test_ingest_audio_marks_call_done_at_end() -> None:
    call = _call()
    with _patched_pipeline(call) as mocks:
        ingest_audio(Path("/tmp/audio.wav"))
    statuses = [c.args[1] for c in mocks["update_status"].call_args_list]
    assert statuses == ["transcribing", "extracting", "done"]


def test_ingest_audio_invokes_on_step_for_each_phase() -> None:
    call = _call()
    messages: list[str] = []
    with _patched_pipeline(call):
        ingest_audio(Path("/tmp/audio.wav"), on_step=messages.append)
    assert len(messages) == 4
    assert "Registrando" in messages[0]
    assert "Transcribiendo" in messages[1]
    assert "Extrayendo" in messages[2]
    assert "Vault" in messages[3]


def test_ingest_audio_works_without_on_step_callback() -> None:
    """Si `on_step=None`, el pipeline no debe romper."""
    call = _call()
    with _patched_pipeline(call):
        result = ingest_audio(Path("/tmp/audio.wav"))
    assert result is not None


def test_ingest_audio_passes_call_to_transcribe() -> None:
    call = _call()
    with _patched_pipeline(call) as mocks:
        ingest_audio(Path("/tmp/audio.wav"))
    assert mocks["transcribe"].call_args.args[0] is call


def test_ingest_audio_writes_call_index_with_status_done() -> None:
    call = _call()
    with _patched_pipeline(call) as mocks:
        ingest_audio(Path("/tmp/audio.wav"))
    # Primer arg posicional de write_call_index es el `Call`.
    final_call_passed = mocks["write_index"].call_args.args[0]
    assert final_call_passed.status == "done"
    assert final_call_passed.id == call.id
