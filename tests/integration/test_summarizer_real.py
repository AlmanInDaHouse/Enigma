"""Integration test: resumen ejecutivo real de una llamada (T-401).

Marcado `@pytest.mark.integration`. Requiere Ollama corriendo con
`qwen2.5:7b`. Usa una SQLite y un Vault temporales.

    uv run pytest -m integration tests/integration/test_summarizer_real.py
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from enigma.agent.summarizer import summarize_call
from enigma.config import settings
from enigma.db import calls as calls_db
from enigma.db.sqlite import get_connection
from enigma.ingest.transcriber import save_transcript
from enigma.models.call import Call
from enigma.models.transcript import Transcript, TranscriptSegment

_TRANSCRIPT_LINES = [
    "Buenos días, hoy revisamos la estrategia de captación de socios del club.",
    "Propongo centrarnos en los barrios con más densidad de clubes de pádel.",
    "De acuerdo, y además deberíamos lanzar una clase de prueba gratuita.",
    "Sobre precios: un descuento por volumen subiría el ticket medio.",
    "Perfecto, entonces decidimos: campaña en esos barrios y clase gratis.",
    "Yo me encargo de preparar la campaña para la semana que viene.",
]


@pytest.fixture
def temp_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Call]:
    """SQLite + Vault temporales con una llamada y su transcript persistidos."""
    monkeypatch.setattr(settings, "enigma_data_path", tmp_path / "data")
    monkeypatch.setattr(settings, "enigma_vault_path", tmp_path / "vault")

    call = Call(
        id=uuid4(),
        content_hash=uuid4().hex + uuid4().hex,
        title="Estrategia de captación",
        audio_path=tmp_path / "audio.wav",
        duration_seconds=360.0,
        language="es",
        recorded_at=datetime(2026, 5, 14, 10, 0, tzinfo=UTC),
        ingested_at=datetime.now(tz=UTC),
    )
    with get_connection() as conn:
        calls_db.insert_call(conn, call)

    transcript = Transcript(
        call_id=call.id,
        model="faster-whisper:large-v3",
        language="es",
        segments=[
            TranscriptSegment(start=float(i * 5), end=float(i * 5 + 5), text=line)
            for i, line in enumerate(_TRANSCRIPT_LINES)
        ],
        created_at=datetime.now(tz=UTC),
    )
    save_transcript(transcript)
    yield call


@pytest.mark.integration
def test_summarize_call_writes_structured_note(temp_env: Call) -> None:
    result = summarize_call(temp_env.id)

    assert result.summary_path.exists()
    assert result.summary_path.parent == settings.enigma_vault_path / "calls"

    content = result.summary_path.read_text(encoding="utf-8")
    assert "type: call-summary" in content
    assert "## TL;DR" in content
    assert "## Puntos clave" in content
    assert "## Temas tratados" in content
    assert "> Llamada: [[" in content

    # El LLM debe producir un resumen no vacío.
    assert result.summary.tldr.strip()
    assert result.summary.key_points
