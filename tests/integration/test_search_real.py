"""Integration test: búsqueda semántica real contra Qdrant (T-301, RF-07).

Marcado `@pytest.mark.integration`. Requiere Qdrant corriendo y Ollama con
`nomic-embed-text`. Usa un Vault temporal y una colección Qdrant efímera.

    uv run pytest -m integration tests/integration/test_search_real.py
"""

import hashlib
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from enigma.config import settings
from enigma.models.note import Note, NoteSource
from enigma.search import search_notes
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
def indexed_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Vault temporal con 3 notas vectorizadas; limpia la colección al final."""
    collection = f"enigma_test_{uuid4().hex[:8]}"
    monkeypatch.setattr(settings, "enigma_vault_path", tmp_path)
    monkeypatch.setattr(settings, "qdrant_collection", collection)
    write_notes_to_inbox(
        [
            _note("Estrategia padel", "Los clubs de padel tienen alta densidad de socios."),
            _note("Pricing por volumen", "El descuento por volumen sube el ticket medio."),
            _note("Cocina mediterránea", "El aceite de oliva es la base de la dieta."),
        ],
        vault_path=tmp_path,
    )
    reindex_vault()
    try:
        yield collection
    finally:
        client = get_client()
        if client.collection_exists(collection):
            client.delete_collection(collection)


@pytest.mark.integration
def test_search_returns_most_relevant_note_first(indexed_vault: str) -> None:
    results = search_notes("captación de socios para clubes deportivos", top_k=3)
    assert len(results) == 3
    assert results[0].title == "Estrategia padel"
    assert results[0].score >= results[-1].score


@pytest.mark.integration
def test_search_respects_top_k(indexed_vault: str) -> None:
    results = search_notes("cualquier cosa", top_k=2)
    assert len(results) == 2


@pytest.mark.integration
def test_search_latency_under_3s(indexed_vault: str) -> None:
    """Una búsqueda (embed + query Qdrant) está holgadamente bajo el p95 < 3s."""
    start = time.perf_counter()
    search_notes("aceite de oliva y dieta saludable", top_k=5)
    assert time.perf_counter() - start < 3.0
