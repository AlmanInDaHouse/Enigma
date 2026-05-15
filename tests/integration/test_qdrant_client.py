"""Tests CRUD para `enigma.vector.qdrant_client` contra Qdrant local (T-201).

Todos `@pytest.mark.integration` — requieren Qdrant corriendo
(`docker compose up -d qdrant`). Cada test usa una colección efímera
`enigma_test_<rand>` que se borra al final, sin tocar la colección de
producción `enigma_notes`.

Correr local:  `uv run pytest -m integration tests/integration/test_qdrant_client.py`
"""

from collections.abc import Iterator
from uuid import uuid4

import pytest

from enigma.vector.qdrant_client import (
    VECTOR_SIZE,
    SearchHit,
    count,
    delete_vector,
    ensure_collection,
    get_client,
    search,
    upsert_vector,
)


@pytest.fixture
def collection() -> Iterator[str]:
    """Colección efímera de Qdrant; se elimina al terminar el test."""
    name = f"enigma_test_{uuid4().hex[:8]}"
    client = get_client()
    ensure_collection(client=client, collection=name)
    try:
        yield name
    finally:
        client.delete_collection(name)


def _vec(seed: float) -> list[float]:
    """Vector de 768 dims constante (`seed`) — suficiente para tests CRUD."""
    return [seed] * VECTOR_SIZE


@pytest.mark.integration
def test_ensure_collection_is_idempotent(collection: str) -> None:
    """Llamar `ensure_collection` dos veces no falla ni recrea."""
    client = get_client()
    ensure_collection(client=client, collection=collection)  # 2ª vez
    assert client.collection_exists(collection)


@pytest.mark.integration
def test_upsert_then_count(collection: str) -> None:
    assert count(collection=collection) == 0
    upsert_vector(uuid4(), _vec(0.1), {"title": "uno"}, collection=collection)
    assert count(collection=collection) == 1


@pytest.mark.integration
def test_upsert_is_idempotent_per_note_id(collection: str) -> None:
    """Reupsert del mismo `note_id` reemplaza, no duplica."""
    note_id = uuid4()
    upsert_vector(note_id, _vec(0.1), {"title": "v1"}, collection=collection)
    upsert_vector(note_id, _vec(0.2), {"title": "v2"}, collection=collection)
    assert count(collection=collection) == 1


@pytest.mark.integration
def test_search_returns_hits_with_payload(collection: str) -> None:
    note_id = uuid4()
    upsert_vector(
        note_id,
        _vec(0.5),
        {"title": "Estrategia padel", "status": "draft"},
        collection=collection,
    )
    hits = search(_vec(0.5), top_k=5, collection=collection)
    assert len(hits) == 1
    hit = hits[0]
    assert isinstance(hit, SearchHit)
    assert hit.note_id == note_id
    assert hit.payload["title"] == "Estrategia padel"
    assert 0.0 <= hit.score <= 1.0 + 1e-6


@pytest.mark.integration
def test_search_on_missing_collection_returns_empty() -> None:
    """Buscar en una colección inexistente devuelve `[]`, no falla (T-305)."""
    missing = f"enigma_test_missing_{uuid4().hex[:8]}"
    assert search(_vec(0.5), top_k=5, collection=missing) == []


@pytest.mark.integration
def test_search_respects_top_k(collection: str) -> None:
    for i in range(5):
        upsert_vector(uuid4(), _vec(0.1 * (i + 1)), {"i": i}, collection=collection)
    hits = search(_vec(0.3), top_k=3, collection=collection)
    assert len(hits) == 3


@pytest.mark.integration
def test_search_orders_by_score_descending(collection: str) -> None:
    for i in range(4):
        upsert_vector(uuid4(), _vec(0.1 * (i + 1)), {"i": i}, collection=collection)
    hits = search(_vec(0.25), top_k=4, collection=collection)
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)


@pytest.mark.integration
def test_delete_removes_vector(collection: str) -> None:
    note_id = uuid4()
    upsert_vector(note_id, _vec(0.1), {"title": "borrable"}, collection=collection)
    assert count(collection=collection) == 1
    delete_vector(note_id, collection=collection)
    assert count(collection=collection) == 0


@pytest.mark.integration
def test_delete_missing_id_does_not_raise(collection: str) -> None:
    """Borrar un `note_id` inexistente es un no-op silencioso."""
    delete_vector(uuid4(), collection=collection)
    assert count(collection=collection) == 0
