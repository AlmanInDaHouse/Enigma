"""Tests unitarios para `enigma.ingest.diarizer` con el pipeline pyannote mockeado.

El test real (descarga del modelo + diarización) vive en
`tests/integration/test_diarize_real.py` con marker `@pytest.mark.integration`.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from enigma.ingest.diarizer import (
    DiarizationError,
    DiarizationTurn,
    _get_pipeline,
    diarize_audio,
)

# ── DiarizationTurn ─────────────────────────────────────────────────────────


def test_turn_valid() -> None:
    turn = DiarizationTurn(start=0.0, end=5.0, speaker="SPEAKER_00")
    assert turn.speaker == "SPEAKER_00"


def test_turn_rejects_negative_start() -> None:
    with pytest.raises(ValidationError):
        DiarizationTurn(start=-1.0, end=5.0, speaker="SPEAKER_00")


def test_turn_rejects_extra_fields() -> None:
    kwargs: dict[str, object] = {
        "start": 0.0,
        "end": 5.0,
        "speaker": "SPEAKER_00",
        "extra": "boom",
    }
    with pytest.raises(ValidationError):
        DiarizationTurn(**kwargs)  # type: ignore[arg-type]


# ── diarize_audio (pipeline mockeado) ───────────────────────────────────────


def _fake_pipeline(tracks: list[tuple[float, float, str]]) -> MagicMock:
    """Construye un pipeline pyannote 4.0 falso a partir de (start, end, speaker).

    El pipeline real devuelve un `DiarizeOutput` cuya `.speaker_diarization`
    es la `Annotation` con `itertracks`.
    """
    annotation = MagicMock()
    annotation.itertracks.return_value = [
        (MagicMock(start=start, end=end), None, speaker) for start, end, speaker in tracks
    ]
    output = MagicMock()
    output.speaker_diarization = annotation
    return MagicMock(return_value=output)


def test_diarize_audio_maps_tracks_to_turns() -> None:
    pipeline = _fake_pipeline(
        [
            (0.0, 5.0, "SPEAKER_00"),
            (5.0, 9.0, "SPEAKER_01"),
        ]
    )
    with patch("enigma.ingest.diarizer._get_pipeline", return_value=pipeline):
        turns = diarize_audio(Path("/tmp/audio.wav"))

    assert len(turns) == 2
    assert turns[0].speaker == "SPEAKER_00"
    assert turns[1].speaker == "SPEAKER_01"
    assert all(isinstance(t, DiarizationTurn) for t in turns)


def test_diarize_audio_sorts_turns_by_start() -> None:
    """Aunque pyannote devuelva los tracks desordenados, salen ordenados."""
    pipeline = _fake_pipeline(
        [
            (8.0, 12.0, "SPEAKER_01"),
            (0.0, 4.0, "SPEAKER_00"),
            (4.0, 8.0, "SPEAKER_00"),
        ]
    )
    with patch("enigma.ingest.diarizer._get_pipeline", return_value=pipeline):
        turns = diarize_audio(Path("/tmp/audio.wav"))

    assert [t.start for t in turns] == [0.0, 4.0, 8.0]


def test_diarize_audio_empty_when_no_speech() -> None:
    pipeline = _fake_pipeline([])
    with patch("enigma.ingest.diarizer._get_pipeline", return_value=pipeline):
        turns = diarize_audio(Path("/tmp/silence.wav"))
    assert turns == []


def test_diarize_audio_passes_audio_path_to_pipeline() -> None:
    pipeline = _fake_pipeline([])
    with patch("enigma.ingest.diarizer._get_pipeline", return_value=pipeline):
        diarize_audio(Path("/tmp/specific.wav"))
    pipeline.assert_called_once()
    assert "specific.wav" in str(pipeline.call_args.args[0])


# ── _get_pipeline error handling ────────────────────────────────────────────


def test_get_pipeline_raises_when_pyannote_returns_none() -> None:
    """Si `Pipeline.from_pretrained` devuelve None, se eleva DiarizationError."""
    _get_pipeline.cache_clear()
    with patch("pyannote.audio.Pipeline.from_pretrained", return_value=None):
        with pytest.raises(DiarizationError, match="devolvió None"):
            _get_pipeline("pyannote/does-not-resolve", "fake-token")
    _get_pipeline.cache_clear()
