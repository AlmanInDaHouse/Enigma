"""Embedder con Ollama `nomic-embed-text` para vectorizar notas (T-202).

`embed_text` produce un vector de 768 dimensiones vía la API de embeddings
de Ollama. El cliente se cachea por proceso. `embed_note` embebe el **cuerpo**
de una nota (no el título): el cuerpo es lo que define su semántica para
búsqueda y para la detección de wikilinks.
"""

from functools import lru_cache

import ollama

from enigma.config import settings
from enigma.models.note import Note

EMBEDDING_DIM = 768
"""Dimensión de los vectores de `nomic-embed-text` (coincide con Qdrant)."""


@lru_cache(maxsize=1)
def _client() -> ollama.Client:
    """Cliente Ollama cacheado, apuntando a `settings.ollama_host`."""
    return ollama.Client(host=settings.ollama_host)


def embed_text(text: str, *, model: str | None = None) -> list[float]:
    """Devuelve el embedding de `text` vía Ollama.

    Args:
        text: Texto a embeber.
        model: Override del modelo de embeddings. Por defecto
            `settings.ollama_embed_model` (`nomic-embed-text`).

    Returns:
        Vector de floats de longitud `EMBEDDING_DIM` (768).
    """
    effective_model = model or settings.ollama_embed_model
    response = _client().embed(model=effective_model, input=text)
    return list(response["embeddings"][0])


def embed_note(note: Note, *, model: str | None = None) -> list[float]:
    """Embebe el cuerpo (`note.body`) de una nota atómica.

    Se embebe el cuerpo y no el título porque es el cuerpo el que carga la
    idea; los vecinos semánticos y los wikilinks (T-205) se calculan sobre él.
    """
    return embed_text(note.body, model=model)
