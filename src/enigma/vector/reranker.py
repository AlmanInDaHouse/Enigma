"""Reranking de notas con un cross-encoder local (T-304).

La búsqueda vectorial (T-301) ordena por similitud coseno entre embeddings
*bi-encoder*: rápida, pero el embedding de la query y el del documento se
calculan por separado. Un **cross-encoder** procesa el par `(query, cuerpo)`
junto y produce un score de relevancia más fino — a costa de no poder
indexar, así que solo se aplica sobre un pool ya recuperado.

`rerank_notes()` carga el modelo `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`
(multilingüe, entrenado en mMARCO — apto para español) vía
`sentence-transformers`. El modelo se descarga una vez de HuggingFace y luego
corre 100% local; el objeto se cachea por proceso.

`sentence-transformers` se importa de forma perezosa dentro de `_encoder`:
es una dependencia pesada (arrastra `transformers`) y así importar este
módulo — p.ej. para mockearlo en tests — no la carga. El `CrossEncoder` se
trata como `Any` a propósito: sus overloads de `predict` (audio/imagen/vídeo)
hacen que mypy rechace un `list[tuple[str, str]]` legítimo, y el tipo solo
estaría disponible en los entornos donde el paquete está instalado.
"""

from functools import lru_cache
from typing import Any

from enigma.config import settings
from enigma.models.note import Note


@lru_cache(maxsize=2)
def _encoder(model: str) -> Any:
    """Carga (y cachea) el cross-encoder. Descarga el modelo en la 1ª llamada."""
    from sentence_transformers import CrossEncoder

    return CrossEncoder(model)


def rerank_notes(query: str, notes: list[Note], *, model: str | None = None) -> list[Note]:
    """Reordena `notes` por relevancia a `query` con el cross-encoder local.

    Args:
        query: Consulta en lenguaje natural.
        notes: Notas a reordenar (típicamente el pool recuperado por
            búsqueda vectorial).
        model: Override del modelo. Default `settings.rerank_model`.

    Returns:
        Las mismas notas reordenadas por score de relevancia descendente.
        Lista vacía si `notes` está vacía. El orden relativo de notas con
        el mismo score es estable (Python `sorted`).
    """
    if not notes:
        return []

    encoder = _encoder(model or settings.rerank_model)
    pairs = [(query, note.body) for note in notes]
    scores: Any = encoder.predict(pairs)
    ranked = sorted(zip(notes, scores, strict=True), key=lambda pair: pair[1], reverse=True)
    return [note for note, _ in ranked]
