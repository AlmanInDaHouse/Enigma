"""Integration test: brainstorming real de una llamada (T-704).

Marcado `@pytest.mark.integration`. Requiere Ollama corriendo con
`qwen2.5:7b`. Usa una SQLite y un Vault temporales.

    uv run pytest -m integration tests/integration/test_brainstorm_real.py
"""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from enigma.agent.brainstorm import Brainstorm, brainstorm_call
from enigma.config import settings
from enigma.db import calls as calls_db
from enigma.db.sqlite import get_connection
from enigma.ingest.transcriber import save_transcript
from enigma.models.call import Call
from enigma.models.transcript import Transcript, TranscriptSegment

_TRANSCRIPT_LINES = [
    "Hoy hablamos de cómo captar más socios para el club de pádel.",
    "La idea es lanzar una campaña en los barrios con más densidad de pistas.",
    "También valoramos ofrecer una clase de prueba gratuita a los nuevos.",
    "Nos preocupa el coste de adquisición y si el boca a boca será suficiente.",
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
def test_brainstorm_call_expands_the_call(temp_corpus: Call) -> None:
    result = brainstorm_call(temp_corpus.id)

    assert isinstance(result, Brainstorm)
    assert result.call_id == temp_corpus.id

    # El LLM debería aportar ideas en al menos una de las cuatro categorías.
    total = result.analogies + result.next_steps + result.open_questions + result.risks
    assert total, "se esperaba al menos una idea de brainstorming"
