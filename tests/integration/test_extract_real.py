"""Integration test: extracción real contra Ollama local con `qwen2.5:7b`.

Marcado `@pytest.mark.integration`. Excluido del CI por defecto. Para
correrlo local:

    uv run pytest -m integration tests/integration/test_extract_real.py

Pre-requisitos:
- Ollama corriendo en `settings.ollama_host`.
- El modelo configurado en `settings.ollama_llm_model` debe estar disponible
  (`ollama list` lo muestra).
"""

from uuid import uuid4

import pytest

from enigma.extract.chunker import TranscriptChunk
from enigma.extract.extractor import extract_notes_from_chunk


@pytest.mark.integration
def test_extract_real_chunk_returns_at_least_one_note() -> None:
    """El extractor produce al menos una nota con un chunk plausible en español."""
    chunk = TranscriptChunk(
        text=(
            "[SPEAKER_00] Hemos decidido enfocarnos en clubs de padel "
            "con más de cien socios activos.\n"
            "[SPEAKER_01] Y el ticket medio sube si ofrecemos personalización "
            "individual dentro del diseño del club.\n"
            "[SPEAKER_00] Vale, lo añadimos al pitch."
        ),
        timestamp_start=120.0,
        timestamp_end=210.5,
        segment_start_index=0,
        segment_end_index=2,
        token_count=80,
    )

    notes = extract_notes_from_chunk(chunk, call_id=uuid4())

    assert len(notes) >= 1
    for n in notes:
        assert n.title
        assert n.body
        assert n.status == "draft"
        assert n.source.timestamp_start >= 0.0
        assert len(n.content_hash) == 64
