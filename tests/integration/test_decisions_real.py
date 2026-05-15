"""Integration test: índice de decisiones real (T-402).

Marcado `@pytest.mark.integration`. Requiere Ollama corriendo con
`qwen2.5:7b`. Usa una SQLite y un Vault temporales.

    uv run pytest -m integration tests/integration/test_decisions_real.py
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from enigma.agent.decisions import build_decision_index
from enigma.config import settings
from enigma.db import calls as calls_db
from enigma.db.sqlite import get_connection
from enigma.ingest.transcriber import save_transcript
from enigma.models.call import Call
from enigma.models.transcript import Transcript, TranscriptSegment

_TRANSCRIPT_LINES = [
    "Hoy revisamos la estrategia de captación de socios del club.",
    "Decidimos lanzar una campaña en los barrios con más densidad de pádel.",
    "Acordamos también ofrecer una clase de prueba gratuita a los nuevos.",
    "Queda aprobado aplicar un descuento por volumen en los abonos.",
]


@pytest.fixture
def temp_corpus(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Call]:
    """SQLite + Vault temporales con una llamada y su transcript persistidos."""
    monkeypatch.setattr(settings, "enigma_data_path", tmp_path / "data")
    monkeypatch.setattr(settings, "enigma_vault_path", tmp_path / "vault")

    call = Call(
        id=uuid4(),
        content_hash=uuid4().hex + uuid4().hex,
        title="Estrategia de captación",
        audio_path=tmp_path / "audio.wav",
        duration_seconds=240.0,
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
def test_build_decision_index_writes_index(temp_corpus: Call) -> None:
    result = build_decision_index()

    assert result.index_path == settings.enigma_vault_path / "decisions.md"
    assert result.index_path.exists()
    assert result.calls_scanned == 1

    content = result.index_path.read_text(encoding="utf-8")
    assert "type: decision-index" in content
    assert "# Decisiones" in content

    # La llamada tiene decisiones explícitas: el LLM debe extraer al menos una.
    assert result.decisions, "se esperaba al menos una decisión"
    assert "[[2026-05-14-" in content
