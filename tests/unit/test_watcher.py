"""Tests unitarios para `enigma.workers.watcher` (T-204).

Mockea `read_note` / `embed_note` / `upsert_vector` / `delete_vector` para
verificar la lógica del handler sin tocar Qdrant ni Ollama. El test real con
un `Observer` vivo está en `tests/integration/test_watcher_real.py`.
"""

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from watchdog.events import (
    DirModifiedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
)

from enigma.models.note import Note, NoteSource
from enigma.workers.watcher import VaultEventHandler, vectorize_note_file


def _note() -> Note:
    body = "Cuerpo de la nota."
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


# ── vectorize_note_file ─────────────────────────────────────────────────────


def test_vectorize_note_file_embeds_and_upserts() -> None:
    note = _note()
    with (
        patch("enigma.workers.watcher.read_note", return_value=note),
        patch("enigma.workers.watcher.embed_note", return_value=[0.1] * 768),
        patch("enigma.workers.watcher.upsert_vector") as upsert,
    ):
        result = vectorize_note_file(Path("/vault/inbox/x.md"))
    assert result == note.id
    upsert.assert_called_once()


def test_vectorize_note_file_returns_none_for_invalid_note() -> None:
    with (
        patch("enigma.workers.watcher.read_note", return_value=None),
        patch("enigma.workers.watcher.upsert_vector") as upsert,
    ):
        result = vectorize_note_file(Path("/vault/inbox/bad.md"))
    assert result is None
    upsert.assert_not_called()


# ── VaultEventHandler ───────────────────────────────────────────────────────


def test_handler_on_created_md_vectorizes() -> None:
    handler = VaultEventHandler()
    with patch("enigma.workers.watcher.vectorize_note_file", return_value=uuid4()) as vec:
        handler.on_created(FileCreatedEvent("/vault/inbox/nota.md"))
    vec.assert_called_once()


def test_handler_on_modified_md_vectorizes() -> None:
    handler = VaultEventHandler()
    with patch("enigma.workers.watcher.vectorize_note_file", return_value=uuid4()) as vec:
        handler.on_modified(FileModifiedEvent("/vault/inbox/nota.md"))
    vec.assert_called_once()


def test_handler_ignores_non_markdown_files() -> None:
    handler = VaultEventHandler()
    with patch("enigma.workers.watcher.vectorize_note_file") as vec:
        handler.on_created(FileCreatedEvent("/vault/inbox/foto.png"))
    vec.assert_not_called()


def test_handler_ignores_directory_events() -> None:
    handler = VaultEventHandler()
    with patch("enigma.workers.watcher.vectorize_note_file") as vec:
        handler.on_modified(DirModifiedEvent("/vault/inbox"))
    vec.assert_not_called()


def test_handler_on_deleted_removes_cached_vector() -> None:
    handler = VaultEventHandler()
    note_id = uuid4()
    path = "/vault/inbox/nota.md"
    with patch("enigma.workers.watcher.vectorize_note_file", return_value=note_id):
        handler.on_created(FileCreatedEvent(path))  # cachea path → note_id
    with patch("enigma.workers.watcher.delete_vector") as deleter:
        handler.on_deleted(FileDeletedEvent(path))
    deleter.assert_called_once_with(note_id)


def test_handler_on_deleted_uncached_path_is_noop() -> None:
    handler = VaultEventHandler()
    with patch("enigma.workers.watcher.delete_vector") as deleter:
        handler.on_deleted(FileDeletedEvent("/vault/inbox/nunca-visto.md"))
    deleter.assert_not_called()


def test_handler_vectorize_failure_does_not_propagate() -> None:
    """Una excepción al vectorizar se traga: el watcher no debe morir."""
    handler = VaultEventHandler()
    with patch(
        "enigma.workers.watcher.vectorize_note_file",
        side_effect=RuntimeError("ollama down"),
    ):
        handler.on_modified(FileModifiedEvent("/vault/inbox/nota.md"))  # no raise


def test_handler_caches_note_id_on_successful_vectorize() -> None:
    handler = VaultEventHandler()
    note_id = uuid4()
    path = "/vault/inbox/nota.md"
    with patch("enigma.workers.watcher.vectorize_note_file", return_value=note_id):
        handler.on_modified(FileModifiedEvent(path))
    # El delete posterior debe poder usar el cache.
    with patch("enigma.workers.watcher.delete_vector") as deleter:
        handler.on_deleted(FileDeletedEvent(path))
    deleter.assert_called_once_with(note_id)
