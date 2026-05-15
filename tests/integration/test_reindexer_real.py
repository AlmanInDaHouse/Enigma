"""Integration test: reindexado real del Vault en Qdrant (T-203).

Marcado `@pytest.mark.integration`. Requiere Qdrant corriendo y Ollama con
`nomic-embed-text`. Usa un Vault temporal y una colección Qdrant efímera.

    uv run pytest -m integration tests/integration/test_reindexer_real.py
"""

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from enigma.config import settings
from enigma.models.note import Note, NoteSource
from enigma.vault.writer import write_notes_to_inbox
from enigma.vector.qdrant_client import get_client
from enigma.vector.reindexer import reindex_vault


def _note(title: str, body: str) -> Note:
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
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Vault temporal + colección Qdrant efímera; limpia la colección al final."""
    collection = f"enigma_test_{uuid4().hex[:8]}"
    monkeypatch.setattr(settings, "enigma_vault_path", tmp_path)
    monkeypatch.setattr(settings, "qdrant_collection", collection)
    try:
        yield collection
    finally:
        client = get_client()
        if client.collection_exists(collection):
            client.delete_collection(collection)


@pytest.mark.integration
def test_reindex_vault_real_indexes_all_notes(isolated_env: str) -> None:
    notes = [
        _note("Estrategia padel", "Los clubs de padel tienen alta densidad."),
        _note("Pricing por volumen", "El descuento por volumen sube el ticket medio."),
    ]
    write_notes_to_inbox(notes, vault_path=settings.enigma_vault_path)

    report = reindex_vault()

    assert report.notes_indexed == 2
    assert report.collection_points == 2
    assert report.vector_dim == 768
    assert report.notes_per_second > 0.0


@pytest.mark.integration
def test_reindex_vault_real_is_idempotent(isolated_env: str) -> None:
    """Reejecutar el reindexado no duplica puntos (upsert por note_id)."""
    write_notes_to_inbox(
        [_note("Idea única", "Cuerpo de la idea única.")],
        vault_path=settings.enigma_vault_path,
    )
    first = reindex_vault()
    second = reindex_vault()
    assert first.collection_points == 1
    assert second.collection_points == 1
