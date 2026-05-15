"""Integration test: modo serendipia real (T-406).

Marcado `@pytest.mark.integration`. Requiere Qdrant y Ollama (`qwen2.5:7b` +
`nomic-embed-text`). Usa un Vault temporal y una colección Qdrant efímera.

    uv run pytest -m integration tests/integration/test_serendipity_real.py
"""

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from enigma.agent.serendipity import build_serendipity_index
from enigma.config import settings
from enigma.models.note import Note, NoteSource
from enigma.vault.writer import write_notes_to_inbox
from enigma.vector.qdrant_client import get_client
from enigma.vector.reindexer import reindex_vault

# Notas de dominios distintos pero con conexiones plausibles no obvias
# (densidad / fidelización / boca a boca en contextos diferentes).
_NOTES = [
    "La densidad de clubes de pádel en una zona facilita captar socios nuevos.",
    "Un programa de puntos por fidelidad reduce la rotación de clientes del gimnasio.",
    "El boca a boca entre vecinos es el canal más barato para llenar un curso.",
    "Concentrar las clases en pocas franjas horarias mejora la sensación de ambiente.",
    "Una cafetería concurrida atrae a más gente porque la actividad llama a la actividad.",
    "El mantenimiento preventivo de las pistas evita cierres imprevistos.",
]


def _note(body: str) -> Note:
    return Note(
        id=uuid4(),
        title=body[:40],
        body=body,
        tags=["t"],
        source=NoteSource(call_id=uuid4(), timestamp_start=0.0, timestamp_end=1.0),
        content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        extracted_by="qwen2.5:7b",
        created_at=datetime.now(tz=UTC),
    )


@pytest.fixture
def indexed_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Vault temporal con notas de varios dominios, indexado en Qdrant."""
    collection = f"enigma_test_{uuid4().hex[:8]}"
    monkeypatch.setattr(settings, "enigma_vault_path", tmp_path)
    monkeypatch.setattr(settings, "qdrant_collection", collection)

    write_notes_to_inbox([_note(body) for body in _NOTES], vault_path=tmp_path)
    reindex_vault()
    try:
        yield None
    finally:
        client = get_client()
        if client.collection_exists(collection):
            client.delete_collection(collection)


@pytest.mark.integration
def test_serendipity_index_is_written_and_capped(indexed_vault: None) -> None:
    result = build_serendipity_index()

    assert result.index_path == settings.enigma_vault_path / "serendipity.md"
    assert result.index_path.exists()
    content = result.index_path.read_text(encoding="utf-8")
    assert "type: serendipity-index" in content

    # Nunca más de `serendipity_max_suggestions` (5) conexiones.
    assert len(result.suggestions) <= settings.serendipity_max_suggestions
    # Toda sugerencia conecta dos notas distintas.
    for suggestion in result.suggestions:
        assert suggestion.note_a_id != suggestion.note_b_id
