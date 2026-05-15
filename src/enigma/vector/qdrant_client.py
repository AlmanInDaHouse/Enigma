"""Wrapper de Qdrant para vectorización y búsqueda de notas (T-201).

Encapsula la colección `enigma_notes` (768 dim, distancia Cosine — coincide
con los embeddings de `nomic-embed-text`). Expone el CRUD mínimo que el
Vectorizer y el Agente necesitan: `upsert_vector`, `search`, `delete_vector`,
`count`, más `ensure_collection` (idempotente).

El cliente Qdrant se cachea por proceso. Todas las funciones aceptan
overrides opcionales de `client` y `collection` para facilitar los tests
(colecciones efímeras) sin tocar la de producción.
"""

from functools import lru_cache
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams

from enigma.config import settings
from enigma.models.note import Note

VECTOR_SIZE = 768
"""Dimensión de los embeddings de `nomic-embed-text`."""


class SearchHit(BaseModel):
    """Un resultado de búsqueda semántica en Qdrant."""

    model_config = ConfigDict(extra="forbid")

    note_id: UUID
    score: float
    payload: dict[str, Any]


def note_payload(note: Note) -> dict[str, Any]:
    """Payload Qdrant de una nota (esquema de `data-model.md §5`).

    `note_id` no va en el payload: es el `id` del punto. Lo demás sí, para
    poder filtrar búsquedas por tags, call_id, status, etc.
    """
    return {
        "title": note.title,
        "tags": note.tags,
        "call_id": str(note.source.call_id),
        "created_at": note.created_at.isoformat(),
        "speakers": note.source.speakers,
        "status": note.status,
        "content_hash": note.content_hash,
    }


@lru_cache(maxsize=1)
def get_client() -> QdrantClient:
    """Cliente Qdrant cacheado, apuntando a `settings.qdrant_host:port`."""
    return QdrantClient(host=settings.qdrant_host, port=settings.qdrant_port)


def ensure_collection(
    *,
    client: QdrantClient | None = None,
    collection: str | None = None,
) -> None:
    """Crea la colección si no existe (768 dim, Cosine). Idempotente."""
    qdrant = client or get_client()
    name = collection or settings.qdrant_collection
    if not qdrant.collection_exists(name):
        qdrant.create_collection(
            collection_name=name,
            vectors_config=VectorParams(size=VECTOR_SIZE, distance=Distance.COSINE),
        )


def upsert_vector(
    note_id: UUID,
    vector: list[float],
    payload: dict[str, Any],
    *,
    client: QdrantClient | None = None,
    collection: str | None = None,
) -> None:
    """Inserta o actualiza el vector de una nota (upsert por `note_id`).

    Reescribir el mismo `note_id` reemplaza vector y payload — no duplica.
    """
    qdrant = client or get_client()
    name = collection or settings.qdrant_collection
    qdrant.upsert(
        collection_name=name,
        points=[PointStruct(id=str(note_id), vector=vector, payload=payload)],
    )


def search(
    vector: list[float],
    *,
    top_k: int = 5,
    client: QdrantClient | None = None,
    collection: str | None = None,
) -> list[SearchHit]:
    """Devuelve las `top_k` notas más cercanas al vector de consulta.

    Si la colección no existe todavía (sistema recién instalado, sin
    ninguna nota indexada) devuelve una lista vacía en vez de fallar — así
    `enigma search` y el endpoint `/ask` responden con normalidad antes del
    primer `ingest`/`reindex`.
    """
    qdrant = client or get_client()
    name = collection or settings.qdrant_collection
    if not qdrant.collection_exists(name):
        return []
    response = qdrant.query_points(collection_name=name, query=vector, limit=top_k)
    return [
        SearchHit(
            note_id=UUID(str(point.id)),
            score=point.score,
            payload=point.payload or {},
        )
        for point in response.points
    ]


def delete_vector(
    note_id: UUID,
    *,
    client: QdrantClient | None = None,
    collection: str | None = None,
) -> None:
    """Elimina el vector de una nota por `note_id`. No falla si no existe."""
    qdrant = client or get_client()
    name = collection or settings.qdrant_collection
    qdrant.delete(collection_name=name, points_selector=[str(note_id)])


def count(
    *,
    client: QdrantClient | None = None,
    collection: str | None = None,
) -> int:
    """Número de vectores en la colección."""
    qdrant = client or get_client()
    name = collection or settings.qdrant_collection
    result: int = qdrant.count(collection_name=name).count
    return result
