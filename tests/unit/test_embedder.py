"""Tests unitarios para `enigma.vector.embedder` con el cliente Ollama mockeado.

El test real (Ollama + nomic-embed-text) vive en
`tests/integration/test_embedder_real.py` con marker `@pytest.mark.integration`.
"""

from datetime import UTC, datetime
from hashlib import sha256
from unittest.mock import MagicMock, patch
from uuid import uuid4

from enigma.config import settings
from enigma.models.note import Note, NoteSource
from enigma.vector.embedder import EMBEDDING_DIM, embed_note, embed_text


def _mock_client(vector: list[float]) -> MagicMock:
    """Cliente Ollama falso cuyo `.embed` devuelve `{"embeddings": [vector]}`."""
    client = MagicMock()
    client.embed.return_value = {"embeddings": [vector]}
    return client


def test_embed_text_returns_vector_from_response() -> None:
    vec = [0.1] * EMBEDDING_DIM
    with patch("enigma.vector.embedder._client", return_value=_mock_client(vec)):
        result = embed_text("una frase")
    assert result == vec
    assert len(result) == EMBEDDING_DIM


def test_embed_text_uses_settings_model_by_default() -> None:
    client = _mock_client([0.0] * EMBEDDING_DIM)
    with patch("enigma.vector.embedder._client", return_value=client):
        embed_text("hola")
    assert client.embed.call_args.kwargs["model"] == settings.ollama_embed_model


def test_embed_text_accepts_model_override() -> None:
    client = _mock_client([0.0] * EMBEDDING_DIM)
    with patch("enigma.vector.embedder._client", return_value=client):
        embed_text("hola", model="otro-embedder")
    assert client.embed.call_args.kwargs["model"] == "otro-embedder"


def test_embed_text_passes_input_to_ollama() -> None:
    client = _mock_client([0.0] * EMBEDDING_DIM)
    with patch("enigma.vector.embedder._client", return_value=client):
        embed_text("texto concreto")
    assert client.embed.call_args.kwargs["input"] == "texto concreto"


def test_embed_note_embeds_the_body() -> None:
    body = "Los clubs de padel tienen alta densidad de socios."
    note = Note(
        id=uuid4(),
        title="Título distinto del cuerpo",
        body=body,
        tags=["t"],
        source=NoteSource(call_id=uuid4(), timestamp_start=0.0, timestamp_end=1.0),
        content_hash=sha256(body.encode("utf-8")).hexdigest(),
        extracted_by="qwen2.5:7b",
        created_at=datetime.now(tz=UTC),
    )
    client = _mock_client([0.2] * EMBEDDING_DIM)
    with patch("enigma.vector.embedder._client", return_value=client):
        embed_note(note)
    # Se embebe el body, no el title.
    assert client.embed.call_args.kwargs["input"] == body
