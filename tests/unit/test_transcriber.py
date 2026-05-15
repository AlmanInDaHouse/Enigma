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
from enigma.ingest.diarizer import DiarizationTurn
from enigma.ingest.transcriber import (
    _confidence_from_logprob,
    _dominant_speaker,
    _resolve_compute_type,
    _resolve_device,
    assign_speakers,
    transcribe,
)
from enigma.models.call import Call
from enigma.models.transcript import Transcript, TranscriptSegment


def _make_call(language: str = "es") -> Call:
    return Call(
        id=uuid4(),
        content_hash="a" * 64,
        audio_path=Path("/tmp/fake.wav"),
        language=language,
        recorded_at=datetime.now(tz=UTC),
        ingested_at=datetime.now(tz=UTC),
    )


# ── device / compute_type resolution ───────────────────────────────────────


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
    very_low = _confidence_from_logprob(-100.0)
    assert very_low is not None
    assert 0.0 <= very_low < 0.01
    assert _confidence_from_logprob(0.0) == 1.0
    assert _confidence_from_logprob(5.0) == 1.0


# ── transcribe (Whisper, sin diarización) ───────────────────────────────────


def test_transcribe_maps_segments_correctly() -> None:
    """`transcribe()` convierte segmentos de WhisperModel a `TranscriptSegment`."""
    fake_segment = MagicMock(start=0.0, end=1.5, text="  hola mundo  ", avg_logprob=-0.5)
    fake_info = MagicMock(language="es")

    fake_model = MagicMock()
    fake_model.transcribe.return_value = (iter([fake_segment]), fake_info)

    with patch("enigma.ingest.transcriber._get_model", return_value=fake_model):
        call = _make_call()
        result = transcribe(call, model_size="tiny", diarize=False)

    assert result.call_id == call.id
    assert result.model == "faster-whisper:tiny"
    assert result.language == "es"
    assert result.diarization_model is None
    assert len(result.segments) == 1

    seg = result.segments[0]
    assert seg.start == 0.0
    assert seg.end == 1.5
    assert seg.text == "hola mundo"
    assert seg.speaker is None
    assert seg.confidence is not None
    assert 0.0 < seg.confidence <= 1.0


def test_transcribe_passes_language_and_vad_filter_to_whisper() -> None:
    fake_model = MagicMock()
    fake_model.transcribe.return_value = (iter([]), MagicMock(language="es"))

    with patch("enigma.ingest.transcriber._get_model", return_value=fake_model):
        transcribe(_make_call(language="es"), model_size="tiny", diarize=False)

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
        result = transcribe(_make_call(), diarize=False)

    assert result.model == "faster-whisper:small"
    assert mocked_get.call_args.args[0] == "small"


# ── _dominant_speaker ───────────────────────────────────────────────────────


def test_dominant_speaker_none_when_no_overlap() -> None:
    turns = [DiarizationTurn(start=10.0, end=20.0, speaker="SPEAKER_00")]
    assert _dominant_speaker(0.0, 5.0, turns) is None


def test_dominant_speaker_single_overlapping_turn() -> None:
    turns = [DiarizationTurn(start=0.0, end=10.0, speaker="SPEAKER_00")]
    assert _dominant_speaker(2.0, 4.0, turns) == "SPEAKER_00"


def test_dominant_speaker_picks_largest_overlap() -> None:
    """Un segmento que toca dos turnos se queda con el de mayor solapamiento."""
    turns = [
        DiarizationTurn(start=0.0, end=5.0, speaker="SPEAKER_00"),
        DiarizationTurn(start=5.0, end=20.0, speaker="SPEAKER_01"),
    ]
    # Segmento [4, 12]: solapa 1s con _00 y 7s con _01.
    assert _dominant_speaker(4.0, 12.0, turns) == "SPEAKER_01"


def test_dominant_speaker_empty_turns() -> None:
    assert _dominant_speaker(0.0, 5.0, []) is None


# ── assign_speakers ─────────────────────────────────────────────────────────


def _transcript_with_segments(*segs: TranscriptSegment) -> Transcript:
    return Transcript(
        call_id=uuid4(),
        model="faster-whisper:tiny",
        created_at=datetime.now(tz=UTC),
        segments=list(segs),
    )


def test_assign_speakers_empty_turns_returns_transcript_unchanged() -> None:
    t = _transcript_with_segments(TranscriptSegment(start=0.0, end=1.0, text="hola"))
    assert assign_speakers(t, []) is t


def test_assign_speakers_fills_speaker_per_segment() -> None:
    transcript = _transcript_with_segments(
        TranscriptSegment(start=0.0, end=4.0, text="primero"),
        TranscriptSegment(start=6.0, end=9.0, text="segundo"),
    )
    turns = [
        DiarizationTurn(start=0.0, end=5.0, speaker="SPEAKER_00"),
        DiarizationTurn(start=5.0, end=12.0, speaker="SPEAKER_01"),
    ]
    result = assign_speakers(transcript, turns)
    assert result.segments[0].speaker == "SPEAKER_00"
    assert result.segments[1].speaker == "SPEAKER_01"


def test_assign_speakers_does_not_mutate_original() -> None:
    transcript = _transcript_with_segments(
        TranscriptSegment(start=0.0, end=4.0, text="hola"),
    )
    turns = [DiarizationTurn(start=0.0, end=5.0, speaker="SPEAKER_00")]
    assign_speakers(transcript, turns)
    assert transcript.segments[0].speaker is None  # original intacto


# ── transcribe con diarización ──────────────────────────────────────────────


def test_transcribe_with_diarize_true_fills_speakers() -> None:
    fake_segment = MagicMock(start=0.0, end=4.0, text="hola", avg_logprob=-0.3)
    fake_model = MagicMock()
    fake_model.transcribe.return_value = (iter([fake_segment]), MagicMock(language="es"))
    fake_turns = [DiarizationTurn(start=0.0, end=10.0, speaker="SPEAKER_00")]

    with (
        patch("enigma.ingest.transcriber._get_model", return_value=fake_model),
        patch("enigma.ingest.transcriber.diarize_audio", return_value=fake_turns),
    ):
        result = transcribe(_make_call(), model_size="tiny", diarize=True)

    assert result.segments[0].speaker == "SPEAKER_00"
    assert result.diarization_model == settings.diarization_model


def test_transcribe_diarization_failure_is_non_fatal() -> None:
    """Si `diarize_audio` lanza, la transcripción sigue sin speakers."""
    fake_segment = MagicMock(start=0.0, end=4.0, text="hola", avg_logprob=-0.3)
    fake_model = MagicMock()
    fake_model.transcribe.return_value = (iter([fake_segment]), MagicMock(language="es"))

    with (
        patch("enigma.ingest.transcriber._get_model", return_value=fake_model),
        patch(
            "enigma.ingest.transcriber.diarize_audio",
            side_effect=RuntimeError("pyannote down"),
        ),
    ):
        result = transcribe(_make_call(), model_size="tiny", diarize=True)

    assert result.segments[0].speaker is None
    assert result.diarization_model is None


def test_transcribe_diarize_false_skips_pyannote() -> None:
    """Con `diarize=False`, `diarize_audio` no se invoca."""
    fake_model = MagicMock()
    fake_model.transcribe.return_value = (iter([]), MagicMock(language="es"))

    with (
        patch("enigma.ingest.transcriber._get_model", return_value=fake_model),
        patch("enigma.ingest.transcriber.diarize_audio") as mocked_diarize,
    ):
        transcribe(_make_call(), model_size="tiny", diarize=False)

    mocked_diarize.assert_not_called()


def test_transcribe_diarize_none_follows_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`diarize=None` consulta `settings.diarization_enabled`."""
    monkeypatch.setattr(settings, "diarization_enabled", False)
    fake_model = MagicMock()
    fake_model.transcribe.return_value = (iter([]), MagicMock(language="es"))

    with (
        patch("enigma.ingest.transcriber._get_model", return_value=fake_model),
        patch("enigma.ingest.transcriber.diarize_audio") as mocked_diarize,
    ):
        transcribe(_make_call(), model_size="tiny")

    mocked_diarize.assert_not_called()
