"""Integration test: reranking real con el cross-encoder local (T-304).

Marcado `@pytest.mark.integration`. La primera ejecución descarga el modelo
`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (~120 MB) de HuggingFace; luego
corre offline. Importar `sentence-transformers` requiere FFmpeg *shared build*
en el PATH (igual que pyannote):

    SHDIR='/c/Users/manul/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg.Shared_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1.1-full_build-shared/bin'
    PATH="$SHDIR:$PATH" uv run pytest -m integration tests/integration/test_reranker_real.py
"""

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

import pytest

from enigma.models.note import Note, NoteSource
from enigma.vector.reranker import rerank_notes


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


@pytest.mark.integration
def test_rerank_promotes_the_relevant_note() -> None:
    """El cross-encoder coloca primero la nota que responde a la consulta."""
    notes = [
        _note(
            "Cocina mediterránea",
            "El aceite de oliva virgen extra es la base de la dieta mediterránea.",
        ),
        _note(
            "Mantenimiento de pistas",
            "Las pistas de césped artificial necesitan cepillado periódico.",
        ),
        _note(
            "Captación de socios",
            "Para captar nuevos socios conviene ofrecer una clase de prueba "
            "gratuita y campañas de recomendación entre los jugadores actuales.",
        ),
    ]
    ranked = rerank_notes("¿Cómo conseguimos más socios para el club?", notes)
    assert ranked[0].title == "Captación de socios"


@pytest.mark.integration
def test_rerank_fixes_a_bad_baseline_order() -> None:
    """Reranking corrige un orden inicial (baseline) deliberadamente malo.

    Simula el caso de T-304: la nota relevante llega en última posición del
    pool recuperado; tras el reranking sube al top.
    """
    relevant = _note(
        "Descuento por volumen",
        "Aplicar descuentos por volumen sube el ticket medio porque incentiva "
        "compras mayores sin sacrificar el margen unitario.",
    )
    distractor_a = _note(
        "Horario del club",
        "El club abre de lunes a domingo de 8:00 a 23:00 horas.",
    )
    distractor_b = _note(
        "Tipos de raqueta",
        "Las raquetas de pádel se diferencian por forma: redonda, lágrima y diamante.",
    )
    baseline = [distractor_a, distractor_b, relevant]  # relevante al final

    ranked = rerank_notes("¿Qué política de precios sube el ticket medio?", baseline)

    assert ranked[0].title == "Descuento por volumen"
    assert ranked.index(relevant) < baseline.index(relevant)
