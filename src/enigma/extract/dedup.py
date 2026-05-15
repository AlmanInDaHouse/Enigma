"""Deduplicación intra-llamada de notas atómicas (T-108).

Estrategia heurística, **sin embeddings**, hasta que Fase 2 traiga
`nomic-embed-text`. Dos pasadas sobre la lista de notas devuelta por el
extractor:

1. **Exacta por `content_hash`** — el cuerpo es bit-a-bit idéntico.
   Conserva la primera ocurrencia (orden estable).
2. **Aproximada por título** — si dos títulos tienen ratio
   `difflib.SequenceMatcher` ≥ `settings.dedup_similarity_threshold`
   (default 0.92), se consideran la misma idea. De cada clúster se
   conserva la nota con cuerpo más largo (asunción: el LLM detalló
   mejor la idea en una de las pasadas con overlap).

`SequenceMatcher` es stdlib — cero dependencias nuevas. Cuando llegue
Fase 2 con embeddings, esto se reemplaza por similitud coseno sobre el
cuerpo embebido, y el `threshold` se reinterpreta como umbral coseno.
"""

from difflib import SequenceMatcher

from enigma.config import settings
from enigma.models.note import Note


def _title_similarity(a: str, b: str) -> float:
    """Ratio en `[0, 1]` entre dos títulos (case-insensitive, sin más normalización)."""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def dedupe_notes(
    notes: list[Note],
    *,
    threshold: float | None = None,
) -> list[Note]:
    """Devuelve `notes` sin duplicados intra-lista.

    Args:
        notes: Notas extraídas para una misma llamada (de uno o varios chunks).
        threshold: Umbral de similitud de título. Default
            `settings.dedup_similarity_threshold` (0.92).

    Returns:
        Lista deduplicada. Orden preservado por aparición; en clústers
        por título, se conserva la nota con cuerpo más largo.
    """
    cutoff = threshold if threshold is not None else settings.dedup_similarity_threshold

    # Paso 1: dedup exacto por content_hash.
    seen_hashes: set[str] = set()
    unique_by_hash: list[Note] = []
    for note in notes:
        if note.content_hash not in seen_hashes:
            seen_hashes.add(note.content_hash)
            unique_by_hash.append(note)

    # Paso 2: dedup aproximado por título; en empate, gana cuerpo más largo.
    deduped: list[Note] = []
    for candidate in unique_by_hash:
        match_idx: int | None = None
        for idx, existing in enumerate(deduped):
            if _title_similarity(candidate.title, existing.title) >= cutoff:
                match_idx = idx
                break
        if match_idx is None:
            deduped.append(candidate)
        elif len(candidate.body) > len(deduped[match_idx].body):
            deduped[match_idx] = candidate

    return deduped
