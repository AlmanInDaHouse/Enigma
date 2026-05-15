"""Búsqueda semántica de notas en el Vault (T-301, RF-07).

`search_notes(query, top_k)` embebe la consulta con `nomic-embed-text` y
recupera las `top_k` notas más cercanas de Qdrant. El resultado se construye
**solo desde el payload del punto** (título, tags, fecha, estado): no se lee
el cuerpo de las notas ni se recorre el Vault, así la búsqueda es un único
embed + un único query a Qdrant — muy por debajo del presupuesto p95 < 3s.

La cita textual con el cuerpo de la nota es competencia del pipeline RAG
(T-302), que sí lee los ficheros del Vault.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from enigma.vector.embedder import embed_text
from enigma.vector.qdrant_client import SearchHit, search


class SearchResult(BaseModel):
    """Una nota recuperada por búsqueda semántica.

    Se construye desde el payload Qdrant; `call_id` y `created_at` son
    opcionales porque una nota indexada con payload incompleto o malformado
    no debe romper la búsqueda.
    """

    model_config = ConfigDict(extra="forbid")

    note_id: UUID
    title: str
    score: float
    tags: list[str]
    status: str
    call_id: UUID | None
    created_at: datetime | None


def _coerce_uuid(value: object) -> UUID | None:
    """Convierte un valor de payload a `UUID`, o `None` si no es válido."""
    try:
        return UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


def _coerce_datetime(value: object) -> datetime | None:
    """Convierte un valor de payload a `datetime`, o `None` si no es válido."""
    try:
        return datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None


def _result_from_hit(hit: SearchHit) -> SearchResult:
    """Mapea un `SearchHit` de Qdrant a un `SearchResult` (lectura defensiva)."""
    payload = hit.payload
    return SearchResult(
        note_id=hit.note_id,
        title=str(payload.get("title", "(sin título)")),
        score=hit.score,
        tags=list(payload.get("tags") or []),
        status=str(payload.get("status", "draft")),
        call_id=_coerce_uuid(payload.get("call_id")),
        created_at=_coerce_datetime(payload.get("created_at")),
    )


def search_notes(query: str, *, top_k: int = 5) -> list[SearchResult]:
    """Recupera las `top_k` notas semánticamente más cercanas a `query`.

    Args:
        query: Consulta en lenguaje natural.
        top_k: Número máximo de notas a devolver.

    Returns:
        `SearchResult`s ordenados por relevancia descendente (el orden que
        devuelve Qdrant). Lista vacía si no hay notas indexadas.
    """
    vector = embed_text(query)
    hits = search(vector, top_k=top_k)
    return [_result_from_hit(hit) for hit in hits]
