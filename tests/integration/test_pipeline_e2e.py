"""Tests end-to-end del pipeline de ingesta (T-115).

Dos tests, ambos `@pytest.mark.integration` (excluidos del CI):

1. `test_pipeline_e2e_structural` — corre `ingest_audio()` completo sobre
   30 s de silencio generado en runtime. Verifica que la cadena
   register → transcribe → extract → vault no lanza excepción y deja
   los artefactos en disco. NO exige notas (el silencio no produce
   habla extraíble).

2. `test_pipeline_e2e_with_real_audio` — se salta (`skipif`) salvo que
   exista `tests/fixtures/audios/sample_es.wav`. Cuando ese fichero
   está, exige ≥ 1 nota en `vault/inbox/` (criterio de aceptación de
   `specs/001-mvp-core`).

Correr local:  `uv run pytest -m integration tests/integration/test_pipeline_e2e.py`
"""

import wave
from pathlib import Path

import pytest

from enigma.config import settings
from enigma.db import calls as calls_db
from enigma.db.sqlite import get_connection
from enigma.pipeline import IngestResult, ingest_audio

_REAL_AUDIO = Path(__file__).parent.parent / "fixtures" / "audios" / "sample_es.wav"


@pytest.fixture
def silence_wav(tmp_path: Path) -> Path:
    """30 segundos de silencio @ 16 kHz mono PCM."""
    path = tmp_path / "silence30.wav"
    sr = 16000
    silence = b"\x00\x00" * (sr * 30)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sr)
        wav.writeframes(silence)
    return path


@pytest.fixture(autouse=True)
def _isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Aísla `data/` y `vault/` bajo tmp_path y fuerza el modelo Whisper `tiny`."""
    monkeypatch.setattr(settings, "enigma_data_path", tmp_path / "data")
    monkeypatch.setattr(settings, "enigma_vault_path", tmp_path / "vault")
    monkeypatch.setattr(settings, "whisper_model", "tiny")  # rápido para tests


@pytest.mark.integration
def test_pipeline_e2e_structural(silence_wav: Path) -> None:
    """El pipeline completo corre sin excepción sobre 30 s de silencio."""
    result = ingest_audio(silence_wav, title="E2E structural test")

    assert isinstance(result, IngestResult)
    assert result.call.status == "done"
    assert result.transcript_path.exists()
    assert result.call_index_path.exists()
    assert result.call_index_path.parent == settings.enigma_vault_path / "calls"

    # La Call quedó persistida en SQLite con status final.
    with get_connection() as conn:
        stored = calls_db.get_call(conn, result.call.id)
    assert stored is not None
    assert stored.status == "done"


@pytest.mark.integration
@pytest.mark.skipif(
    not _REAL_AUDIO.is_file(),
    reason="Falta el fixture de audio real en tests/fixtures/audios/sample_es.wav",
)
def test_pipeline_e2e_with_real_audio() -> None:
    """Con un audio real en español, el pipeline extrae ≥ 1 nota al `inbox/`."""
    result = ingest_audio(_REAL_AUDIO, title="E2E real audio")

    assert len(result.notes) >= 1
    inbox_files = list((settings.enigma_vault_path / "inbox").glob("*.md"))
    assert len(inbox_files) >= 1
