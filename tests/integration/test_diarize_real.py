"""Integration test: diarización real con pyannote.audio (T-103).

Marcado `@pytest.mark.integration`, excluido del CI. Para correrlo local:

    uv run pytest -m integration tests/integration/test_diarize_real.py

Requiere `PYANNOTE_AUTH_TOKEN` en `.env` y haber aceptado las condiciones de
`pyannote/speaker-diarization-community-1` en huggingface.co. La primera
ejecución descarga los modelos de HuggingFace.
"""

import wave
from pathlib import Path

import pytest

from enigma.ingest.diarizer import DiarizationTurn, diarize_audio


@pytest.fixture
def silence_wav(tmp_path: Path) -> Path:
    """5 segundos de silencio @ 16 kHz mono PCM."""
    path = tmp_path / "silence.wav"
    sr = 16000
    silence = b"\x00\x00" * (sr * 5)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sr)
        wav.writeframes(silence)
    return path


@pytest.mark.integration
def test_diarize_real_silence_returns_turn_list(silence_wav: Path) -> None:
    """Diarizar silencio con pyannote real devuelve una lista de turnos válida."""
    turns = diarize_audio(silence_wav)

    assert isinstance(turns, list)
    # El silencio puede dar 0 turnos; si da alguno, debe estar bien formado.
    for turn in turns:
        assert isinstance(turn, DiarizationTurn)
        assert turn.end >= turn.start
        assert turn.speaker
