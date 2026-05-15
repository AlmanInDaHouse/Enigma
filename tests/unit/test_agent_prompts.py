"""Tests para `enigma.agent.prompts` (T-302)."""

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from enigma.agent.prompts import build_rag_messages
from enigma.models.note import Note, NoteSource
from enigma.vault.writer import note_stem


def _note(title: str = "Estrategia padel", body: str = "Los clubs tienen socios.") -> Note:
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


def test_build_rag_messages_has_system_and_user() -> None:
    messages = build_rag_messages("¿Qué dijimos?", [_note()])
    assert [m["role"] for m in messages] == ["system", "user"]


def test_user_message_includes_question_and_bodies() -> None:
    note = _note(title="Pricing", body="El descuento por volumen sube el ticket.")
    messages = build_rag_messages("¿Cómo subimos el ticket medio?", [note])
    user = messages[1]["content"]
    assert "¿Cómo subimos el ticket medio?" in user
    assert "El descuento por volumen sube el ticket." in user
    assert "Pricing" in user


def test_user_message_carries_resolvable_wikilink_stem() -> None:
    """El bloque de contexto incluye el `[[stem|título]]` con el stem real."""
    note = _note(title="Captación por club")
    messages = build_rag_messages("pregunta", [note])
    stem = note_stem(note.id, note.title)
    assert f"[[{stem}|Captación por club]]" in messages[1]["content"]


def test_build_rag_messages_with_no_notes() -> None:
    messages = build_rag_messages("pregunta sin contexto", [])
    assert len(messages) == 2
    assert "pregunta sin contexto" in messages[1]["content"]
