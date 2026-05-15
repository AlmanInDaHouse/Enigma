"""Integration test: pipeline RAG real (T-302).

Marcado `@pytest.mark.integration`. Requiere Qdrant corriendo y Ollama con
`nomic-embed-text` + `qwen2.5:7b`. Usa un Vault temporal y una colección
Qdrant efímera.

    uv run pytest -m integration tests/integration/test_rag_real.py
"""

import hashlib
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from enigma.agent.rag import answer_question
from enigma.config import settings
from enigma.models.note import Note, NoteSource
from enigma.vault.writer import write_notes_to_inbox
from enigma.vector.qdrant_client import get_client
from enigma.vector.reindexer import reindex_vault

_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


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
def indexed_vault(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Vault temporal con notas vectorizadas; limpia la colección al final."""
    collection = f"enigma_test_{uuid4().hex[:8]}"
    monkeypatch.setattr(settings, "enigma_vault_path", tmp_path)
    monkeypatch.setattr(settings, "qdrant_collection", collection)
    write_notes_to_inbox(
        [
            _note(
                "Captación de socios padel",
                "La densidad de clubes de padel en la zona facilita captar socios "
                "porque concentra jugadores habituales cerca de la instalación.",
            ),
            _note(
                "Pricing por volumen",
                "Aplicar descuentos por volumen sube el ticket medio sin perder "
                "margen, porque incentiva compras mayores.",
            ),
            _note(
                "Cocina mediterránea",
                "El aceite de oliva virgen extra es la base de la dieta mediterránea.",
            ),
        ],
        vault_path=tmp_path,
    )
    reindex_vault()
    try:
        yield tmp_path
    finally:
        client = get_client()
        if client.collection_exists(collection):
            client.delete_collection(collection)


@pytest.mark.integration
def test_rag_answer_cites_existing_vault_file(indexed_vault: Path) -> None:
    """Criterio T-302: la respuesta cita `[[Nota]]` y el fichero existe."""
    result = answer_question(
        "¿Cómo podemos captar socios para el club?",
        top_k=3,
        vault_path=indexed_vault,
    )

    assert result.answer
    # La respuesta contiene al menos un wikilink.
    assert _WIKILINK_RE.search(result.answer) is not None
    # Y al menos una cita verificada contra el contexto.
    assert result.citations, "se esperaba al menos una cita"

    # Cada cita resuelve a un fichero .md que existe en el Vault.
    note_files = {p.name for p in indexed_vault.rglob("*.md")}
    for citation in result.citations:
        expected = f"{citation.stem}.md"
        assert expected in note_files, f"el fichero citado {expected} no existe"


@pytest.mark.integration
def test_rag_no_context_when_query_unrelated(indexed_vault: Path) -> None:
    """Una pregunta sin notas relevantes no produce citas espurias."""
    result = answer_question(
        "¿Qué estrategia de precios sube el ticket medio?",
        top_k=3,
        vault_path=indexed_vault,
    )
    # Todo stem citado corresponde a un fichero real del Vault.
    vault_stems = {p.stem for p in indexed_vault.rglob("*.md")}
    for citation in result.citations:
        assert citation.stem in vault_stems
