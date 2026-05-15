"""Integration test: detección de contradicciones real (T-404).

Marcado `@pytest.mark.integration`. Requiere Qdrant y Ollama (`qwen2.5:7b` +
`nomic-embed-text`). Verifica el criterio de aceptación de T-404: sobre un
test set con contradicciones inyectadas, se detecta **≥ 60 %**.

    uv run pytest -m integration tests/integration/test_contradictions_real.py
"""

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from enigma.agent.contradictions import build_contradiction_index
from enigma.config import settings
from enigma.models.note import Note, NoteSource
from enigma.vault.writer import write_notes_to_inbox
from enigma.vector.qdrant_client import get_client
from enigma.vector.reindexer import reindex_vault

# Cada pareja: dos notas que afirman algo OPUESTO sobre la misma entidad.
_CONTRADICTING_PAIRS = [
    (
        ("Cuota del club", "La cuota mensual de socio del club es de 50 euros."),
        ("Cuota del club", "La cuota mensual de socio del club es de 90 euros."),
    ),
    (
        ("Pistas del club", "El club dispone de ocho pistas de pádel cubiertas."),
        ("Pistas del club", "El club dispone de tres pistas de pádel cubiertas."),
    ),
    (
        ("Torneo de verano", "El torneo de verano del club se celebra en julio."),
        ("Torneo de verano", "El torneo de verano del club se celebra en septiembre."),
    ),
]

# Notas neutras: no deben generar contradicciones espurias.
_NEUTRAL_NOTES = [
    ("Cafetería", "La cafetería del club abre todos los días por la mañana."),
    ("Vestuarios", "Los vestuarios se renovaron con taquillas nuevas el año pasado."),
]


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
def indexed_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[set[frozenset]]:
    """Vault temporal con notas contradictorias + neutras, indexado en Qdrant.

    Devuelve el conjunto de parejas inyectadas (como `frozenset` de `note_id`).
    """
    collection = f"enigma_test_{uuid4().hex[:8]}"
    monkeypatch.setattr(settings, "enigma_vault_path", tmp_path)
    monkeypatch.setattr(settings, "qdrant_collection", collection)

    injected: set[frozenset] = set()
    notes: list[Note] = []
    for (title_a, body_a), (title_b, body_b) in _CONTRADICTING_PAIRS:
        note_a, note_b = _note(title_a, body_a), _note(title_b, body_b)
        notes.extend([note_a, note_b])
        injected.add(frozenset({note_a.id, note_b.id}))
    notes.extend(_note(title, body) for title, body in _NEUTRAL_NOTES)

    write_notes_to_inbox(notes, vault_path=tmp_path)
    reindex_vault()
    try:
        yield injected
    finally:
        client = get_client()
        if client.collection_exists(collection):
            client.delete_collection(collection)


@pytest.mark.integration
def test_detects_at_least_60_percent_of_injected_contradictions(
    indexed_vault: set[frozenset],
) -> None:
    injected = indexed_vault
    result = build_contradiction_index()

    detected = {frozenset({c.note_a_id, c.note_b_id}) for c in result.contradictions}
    hits = len(injected & detected)
    recall = hits / len(injected)

    assert recall >= 0.60, f"recall {recall:.0%} ({hits}/{len(injected)}) < 60%"
    assert result.index_path.exists()
    assert "type: contradiction-index" in result.index_path.read_text(encoding="utf-8")
