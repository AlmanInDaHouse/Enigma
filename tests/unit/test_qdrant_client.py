"""Tests unitarios para `enigma.vector.qdrant_client` — robustez ante Qdrant caído (T-701).

Mockean el `QdrantClient` para verificar que `search` distingue dos estados:
una colección ausente (devuelve `[]`, normal en un sistema sin indexar) frente
a Qdrant inalcanzable (lanza `VectorStoreUnavailableError`, fallo operativo visible).
"""

from unittest.mock import Mock

import pytest
from qdrant_client.http.exceptions import ResponseHandlingException

from enigma.vector.qdrant_client import VectorStoreUnavailableError, search

_QUERY_VECTOR = [0.1] * 768


def test_search_raises_when_qdrant_unreachable_on_collection_exists() -> None:
    """Qdrant caído al sondear la colección → `VectorStoreUnavailableError`."""
    client = Mock()
    client.collection_exists.side_effect = ResponseHandlingException(
        ConnectionError("[WinError 10061] conexión rechazada"),
    )
    with pytest.raises(VectorStoreUnavailableError, match="Qdrant"):
        search(_QUERY_VECTOR, client=client, collection="enigma_notes")


def test_search_raises_when_qdrant_unreachable_on_query() -> None:
    """Qdrant cae entre el `collection_exists` y la query → `VectorStoreUnavailableError`."""
    client = Mock()
    client.collection_exists.return_value = True
    client.query_points.side_effect = ResponseHandlingException(
        ConnectionError("timeout"),
    )
    with pytest.raises(VectorStoreUnavailableError, match="Qdrant"):
        search(_QUERY_VECTOR, client=client, collection="enigma_notes")


def test_search_returns_empty_when_collection_missing() -> None:
    """Colección ausente ≠ Qdrant caído: sigue devolviendo `[]`, sin excepción."""
    client = Mock()
    client.collection_exists.return_value = False
    assert search(_QUERY_VECTOR, client=client, collection="enigma_notes") == []
    client.query_points.assert_not_called()
