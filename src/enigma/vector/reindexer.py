"""Reindexado completo del Vault en Qdrant (T-203).

`reindex_vault()` recorre todas las notas del Vault, las embebe y las
*upsertea* en la colección Qdrant. Es idempotente: cada nota se upsertea
por su `id`, así que reejecutar no duplica puntos.

Devuelve un `ReindexReport` con métricas (notas/s, dimensión, puntos en la
colección) — útiles para validar los RNF-02/03 del SPEC sin reinstrumentar.
"""

import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from enigma.models.note import Note
from enigma.vault.reader import list_vault_notes, read_note
from enigma.vector.embedder import EMBEDDING_DIM, embed_note
from enigma.vector.qdrant_client import count, ensure_collection, upsert_vector


class ReindexReport(BaseModel):
    """Métricas de una pasada de reindexado."""

    model_config = ConfigDict(extra="forbid")

    notes_indexed: int
    elapsed_seconds: float
    notes_per_second: float
    vector_dim: int
    collection_points: int


def _note_payload(note: Note) -> dict[str, Any]:
    """Payload Qdrant de una nota (esquema de `data-model.md §5`)."""
    return {
        "title": note.title,
        "tags": note.tags,
        "call_id": str(note.source.call_id),
        "created_at": note.created_at.isoformat(),
        "speakers": note.source.speakers,
        "status": note.status,
        "content_hash": note.content_hash,
    }


def reindex_vault(*, vault_path: Path | None = None) -> ReindexReport:
    """Vectoriza todas las notas del Vault y las upsertea en Qdrant.

    Args:
        vault_path: Raíz del Vault. Por defecto `settings.enigma_vault_path`.

    Returns:
        `ReindexReport` con las métricas de la pasada.
    """
    ensure_collection()

    summaries = list_vault_notes(vault_path)
    notes = [note for note in (read_note(s.path) for s in summaries) if note is not None]

    start = time.perf_counter()
    for note in notes:
        vector = embed_note(note)
        upsert_vector(note.id, vector, _note_payload(note))
    elapsed = time.perf_counter() - start

    return ReindexReport(
        notes_indexed=len(notes),
        elapsed_seconds=elapsed,
        notes_per_second=len(notes) / elapsed if elapsed > 0 else 0.0,
        vector_dim=EMBEDDING_DIM,
        collection_points=count(),
    )
