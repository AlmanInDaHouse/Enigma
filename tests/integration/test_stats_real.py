"""Integration test: `enigma stats` real (T-504).

Marcado `@pytest.mark.integration`. Requiere Qdrant y Ollama corriendo. Usa
una SQLite, un Vault y una colección Qdrant temporales.

    uv run pytest -m integration tests/integration/test_stats_real.py
"""

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from enigma.config import settings
from enigma.db import calls as calls_db
from enigma.db.sqlite import get_connection
from enigma.models.call import Call
from enigma.models.note import Note, NoteSource
from enigma.stats import gather_stats
from enigma.vault.writer import write_notes_to_inbox
from enigma.vector.qdrant_client import ensure_collection, get_client


def _note(title: str) -> Note:
    body = f"Cuerpo de {title}."
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


@pytest.fixture
def temp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """SQLite + Vault + colección Qdrant temporales con datos de muestra."""
    collection = f"enigma_test_{uuid4().hex[:8]}"
    monkeypatch.setattr(settings, "enigma_data_path", tmp_path / "data")
    monkeypatch.setattr(settings, "enigma_vault_path", tmp_path / "vault")
    monkeypatch.setattr(settings, "qdrant_collection", collection)

    call = Call(
        id=uuid4(),
        content_hash=uuid4().hex + uuid4().hex,
        title="Llamada de prueba",
        audio_path=tmp_path / "audio.wav",
        duration_seconds=1800.0,
        language="es",
        recorded_at=datetime.now(tz=UTC),
        ingested_at=datetime.now(tz=UTC),
        status="done",
    )
    with get_connection() as conn:
        calls_db.insert_call(conn, call)
    write_notes_to_inbox([_note("Idea A"), _note("Idea B")], vault_path=tmp_path / "vault")
    ensure_collection(collection=collection)
    try:
        yield None
    finally:
        client = get_client()
        if client.collection_exists(collection):
            client.delete_collection(collection)


@pytest.mark.integration
def test_gather_stats_real(temp_env: None) -> None:
    stats = gather_stats()

    # Corpus desde la SQLite y el Vault temporales.
    assert stats.corpus.total_calls == 1
    assert stats.corpus.total_notes == 2
    assert stats.corpus.total_audio_hours == 0.5
    assert stats.corpus.qdrant_vectors == 0  # colección creada, aún vacía

    # Sondeo de salud en vivo: Qdrant y Ollama deben responder.
    assert stats.health.qdrant_ok is True
    assert stats.health.ollama_ok is True
    assert stats.health.embed_latency_ms is not None
    assert stats.health.embed_latency_ms > 0.0
