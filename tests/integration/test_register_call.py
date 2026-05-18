"""Tests end-to-end para `register_call`.

Cada test corre en un `tmp_path` aislado para SQLite y `data/audio/`. Genera
una fixture WAV de 1 s en runtime (silencio, 16 kHz, mono PCM) y trabaja
sobre ella.
"""

import wave
from pathlib import Path

import pytest

from enigma.config import settings
from enigma.ingest.audio import (
    SUPPORTED_EXTENSIONS,
    UnsupportedAudioFormatError,
    register_call,
)


@pytest.fixture
def sample_wav(tmp_path: Path) -> Path:
    """1 segundo de silencio @ 16 kHz mono PCM."""
    path = tmp_path / "sample.wav"
    sample_rate = 16000
    silence = b"\x00\x00" * sample_rate
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(silence)
    return path


@pytest.fixture(autouse=True)
def _isolate_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Hace que `settings.enigma_data_path` apunte a `tmp_path/data` por test."""
    monkeypatch.setattr(settings, "enigma_data_path", tmp_path / "data")


def test_register_call_creates_call(sample_wav: Path) -> None:
    call = register_call(sample_wav)
    assert call.status == "pending"
    assert len(call.content_hash) == 64
    assert call.audio_path.exists()
    assert call.audio_path.suffix == ".wav"
    assert call.duration_seconds > 0.0  # ~1 s


def test_register_call_copies_audio_under_data_audio(sample_wav: Path) -> None:
    call = register_call(sample_wav)
    expected_dir = settings.enigma_data_path / "audio"
    assert call.audio_path.parent == expected_dir
    assert call.audio_path.name == f"{call.id}.wav"


def test_register_call_preserves_original_extension(tmp_path: Path) -> None:
    src = tmp_path / "fake.m4a"
    src.write_bytes(b"\x00" * 1024)  # contenido arbitrario; solo importa que exista
    call = register_call(src)
    assert call.audio_path.suffix == ".m4a"
    assert call.audio_path.exists()


def test_register_call_is_idempotent(sample_wav: Path) -> None:
    first = register_call(sample_wav)
    second = register_call(sample_wav)
    assert first.id == second.id
    assert first.content_hash == second.content_hash


def test_register_call_accepts_title(sample_wav: Path) -> None:
    call = register_call(sample_wav, title="Brainstorm 2026-05")
    assert call.title == "Brainstorm 2026-05"


def test_register_call_accepts_webm(tmp_path: Path) -> None:
    """`.webm` (grabaciones del navegador, Fase 6/T-603) se acepta sin error."""
    src = tmp_path / "grabacion.webm"
    src.write_bytes(b"\x00" * 1024)  # contenido arbitrario; la extensión es lo que valida
    call = register_call(src)
    assert call.audio_path.suffix == ".webm"
    assert call.audio_path.exists()


def test_register_call_rejects_unsupported_format(tmp_path: Path) -> None:
    bad = tmp_path / "notes.txt"
    bad.write_text("not audio")
    with pytest.raises(UnsupportedAudioFormatError):
        register_call(bad)


def test_register_call_rejects_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        register_call(tmp_path / "ghost.wav")


def test_supported_extensions_match_rf01() -> None:
    """RF-01: aceptar wav, mp3, m4a, ogg, webm."""
    assert SUPPORTED_EXTENSIONS == frozenset({".wav", ".mp3", ".m4a", ".ogg", ".webm"})
