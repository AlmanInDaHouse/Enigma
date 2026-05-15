"""Integration test: detección de ideas recurrentes real (T-405).

Marcado `@pytest.mark.integration`. Requiere Qdrant y Ollama (`qwen2.5:7b` +
`nomic-embed-text`). Usa un Vault temporal y una colección Qdrant efímera.

    uv run pytest -m integration tests/integration/test_themes_real.py
"""

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from enigma.agent.themes import build_recurring_themes_index
from enigma.config import settings
from enigma.models.note import Note, NoteSource
from enigma.vault.writer import write_notes_to_inbox
from enigma.vector.qdrant_client import get_client
from enigma.vector.reindexer import reindex_vault

# Tres notas afines (idea recurrente) — cada una de una llamada distinta.
_RECURRING = [
    "Captar nuevos socios es clave: conviene ofrecer clases de prueba gratuitas.",
    "Para captar socios funciona bien la recomendación entre jugadores actuales.",
    "La captación de socios mejora con campañas en redes y jornadas de puertas abiertas.",
]

# Notas de ruido sobre temas distintos y sin relación entre sí.
_NOISE = [
    "El sistema de riego del jardín se revisa cada primavera.",
    "La contabilidad del trimestre se cierra a final de mes.",
]


def _note(body: str, *, call_id: UUID) -> Note:
    return Note(
        id=uuid4(),
        title=body[:40],
        body=body,
        tags=["t"],
        source=NoteSource(call_id=call_id, timestamp_start=0.0, timestamp_end=1.0),
        content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        extracted_by="qwen2.5:7b",
        created_at=datetime.now(tz=UTC),
    )


@pytest.fixture
def indexed_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Vault temporal con un tema recurrente + ruido, indexado en Qdrant."""
    collection = f"enigma_test_{uuid4().hex[:8]}"
    monkeypatch.setattr(settings, "enigma_vault_path", tmp_path)
    monkeypatch.setattr(settings, "qdrant_collection", collection)

    # El tema recurrente: 3 notas afines, cada una de una llamada distinta.
    notes = [_note(body, call_id=uuid4()) for body in _RECURRING]
    # Ruido: cada nota de su propia llamada, sin afinidad entre sí.
    notes += [_note(body, call_id=uuid4()) for body in _NOISE]

    write_notes_to_inbox(notes, vault_path=tmp_path)
    reindex_vault()
    try:
        yield None
    finally:
        client = get_client()
        if client.collection_exists(collection):
            client.delete_collection(collection)


@pytest.mark.integration
def test_detects_the_recurring_theme(indexed_vault: None) -> None:
    result = build_recurring_themes_index()

    assert result.index_path == settings.enigma_vault_path / "recurring-themes.md"
    assert result.index_path.exists()
    content = result.index_path.read_text(encoding="utf-8")
    assert "type: recurring-themes-index" in content

    # El cluster de captación (3 notas, 3 llamadas) debe detectarse como tema.
    assert result.themes, "se esperaba al menos una idea recurrente"
    captacion = next(
        (t for t in result.themes if t.note_count >= 3 and t.call_count >= 2),
        None,
    )
    assert captacion is not None, "el tema recurrente de captación no se detectó"
