"""Tests unitarios para `enigma.ingest.transcriber` con `WhisperModel` mockeado.

Los tests reales con descarga de modelo viven en
`tests/integration/test_transcribe_real.py` con marker `@pytest.mark.integration`.
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from enigma.config import settings
from enigma.ingest.transcriber import (
    _confidence_from_logprob,
    _resolve_compute_type,
    _resolve_device,
    transcribe,
)
from enigma.models.call import Call


def _make_call(language: str = "es") -> Call:
    return Call(
        id=uuid4(),
        content_hash="a" * 64,
        audio_path=Path("/tmp/fake.wav"),
        language=language,
        recorded_at=datetime.now(tz=UTC),
        ingested_at=datetime.now(tz=UTC),
    )


def test_resolve_device_auto_falls_back_to_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    """En esta máquina sin CUDA, `auto` resuelve a `cpu`."""
    monkeypatch.setattr(settings, "whisper_device", "auto")
    assert _resolve_device() == "cpu"


def test_resolve_device_respects_explicit_cpu(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "whisper_device", "cpu")
    assert _resolve_device() == "cpu"


def test_resolve_device_respects_explicit_cuda(monkeypatch: pytest.MonkeyPatch) -> None:
    """`device=cuda` se respeta tal cual, sin re-detectar."""
    monkeypatch.setattr(settings, "whisper_device", "cuda")
    assert _resolve_device() == "cuda"


def test_resolve_compute_type_auto_picks_int8_for_cpu(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "whisper_compute_type", "auto")
    assert _resolve_compute_type("cpu") == "int8"


def test_resolve_compute_type_auto_picks_float16_for_cuda(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "whisper_compute_type", "auto")
    assert _resolve_compute_type("cuda") == "float16"


def test_resolve_compute_type_respects_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "whisper_compute_type", "float32")
    assert _resolve_compute_type("cpu") == "float32"


def test_confidence_from_logprob_clamped_to_unit_interval() -> None:
    assert _confidence_from_logprob(None) is None
    # logprob muy negativo → confianza cercana a 0
    very_low = _confidence_from_logprob(-100.0)
    assert very_low is not None
    assert 0.0 <= very_low < 0.01
    # logprob = 0 → confianza = 1
    assert _confidence_from_logprob(0.0) == 1.0
    # logprob positivo (no debería pasar en Whisper) se clampa a 1
    assert _confidence_from_logprob(5.0) == 1.0


def test_transcribe_maps_segments_correctly() -> None:
    """`transcribe()` convierte segmentos de WhisperModel a `TranscriptSegment`."""
    fake_segment = MagicMock(start=0.0, end=1.5, text="  hola mundo  ", avg_logprob=-0.5)
    fake_info = MagicMock(language="es")

    fake_model = MagicMock()
    fake_model.transcribe.return_value = (iter([fake_segment]), fake_info)

    with patch("enigma.ingest.transcriber._get_model", return_value=fake_model):
        call = _make_call()
        result = transcribe(call, model_size="tiny")

    assert result.call_id == call.id
    assert result.model == "faster-whisper:tiny"
    assert result.language == "es"
    assert result.diarization_model is None
    assert len(result.segments) == 1

    seg = result.segments[0]
    assert seg.start == 0.0
    assert seg.end == 1.5
    assert seg.text == "hola mundo"  # se hace strip()
    assert seg.speaker is None
    assert seg.confidence is not None
    assert 0.0 < seg.confidence <= 1.0


def test_transcribe_passes_language_and_vad_filter_to_whisper() -> None:
    fake_model = MagicMock()
    fake_model.transcribe.return_value = (iter([]), MagicMock(language="es"))

    with patch("enigma.ingest.transcriber._get_model", return_value=fake_model):
        transcribe(_make_call(language="es"), model_size="tiny")

    fake_model.transcribe.assert_called_once()
    kwargs = fake_model.transcribe.call_args.kwargs
    assert kwargs["language"] == "es"
    assert kwargs["vad_filter"] is True


def test_transcribe_uses_settings_model_when_no_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sin `model_size`, usa `settings.whisper_model`."""
    monkeypatch.setattr(settings, "whisper_model", "small")
    fake_model = MagicMock()
    fake_model.transcribe.return_value = (iter([]), MagicMock(language="es"))

    with patch("enigma.ingest.transcriber._get_model", return_value=fake_model) as mocked_get:
        result = transcribe(_make_call())

    assert result.model == "faster-whisper:small"
    args = mocked_get.call_args.args
    assert args[0] == "small"
