"""Integration test: transcribir un audio real con modelo `tiny`.

Marcado `@pytest.mark.integration` y excluido del CI por defecto. Para
correrlo local:

    uv run pytest -m integration

La primera ejecución descarga el modelo `tiny` (~75 MB) desde HuggingFace
al caché de faster-whisper (`~/.cache/huggingface/`).
"""

import wave
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from enigma.ingest.transcriber import transcribe
from enigma.models.call import Call


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
def test_transcribe_real_silence_returns_valid_transcript(silence_wav: Path) -> None:
    """Transcribir silencio con `tiny` produce un `Transcript` válido."""
    call = Call(
        id=uuid4(),
        content_hash="b" * 64,
        audio_path=silence_wav,
        language="es",
        recorded_at=datetime.now(tz=UTC),
        ingested_at=datetime.now(tz=UTC),
    )

    transcript = transcribe(call, model_size="tiny")

    assert transcript.call_id == call.id
    assert transcript.model == "faster-whisper:tiny"
    # `vad_filter=True` sobre silencio puede dar 0 segmentos — eso es OK.
    for seg in transcript.segments:
        assert seg.end >= seg.start
        assert seg.speaker is None
