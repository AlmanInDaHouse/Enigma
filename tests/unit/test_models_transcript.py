"""Tests para `enigma.models.transcript`."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from enigma.models.transcript import Transcript, TranscriptSegment


def _valid_segment_kwargs() -> dict[str, Any]:
    return {"start": 0.0, "end": 1.5, "text": "hola"}


def test_segment_minimal_valid_has_optional_defaults() -> None:
    seg = TranscriptSegment(**_valid_segment_kwargs())
    assert seg.speaker is None
    assert seg.confidence is None


def test_segment_rejects_negative_start() -> None:
    kw = _valid_segment_kwargs()
    kw["start"] = -1.0
    with pytest.raises(ValidationError):
        TranscriptSegment(**kw)


def test_segment_rejects_confidence_above_one() -> None:
    kw = _valid_segment_kwargs()
    kw["confidence"] = 1.5
    with pytest.raises(ValidationError):
        TranscriptSegment(**kw)


def test_segment_rejects_confidence_below_zero() -> None:
    kw = _valid_segment_kwargs()
    kw["confidence"] = -0.1
    with pytest.raises(ValidationError):
        TranscriptSegment(**kw)


def test_transcript_minimal_valid() -> None:
    t = Transcript(
        call_id=uuid4(),
        model="faster-whisper:tiny",
        created_at=datetime.now(tz=UTC),
    )
    assert t.segments == []
    assert t.language == "es"
    assert t.diarization_model is None


def test_transcript_with_segments() -> None:
    t = Transcript(
        call_id=uuid4(),
        model="faster-whisper:tiny",
        created_at=datetime.now(tz=UTC),
        segments=[
            TranscriptSegment(start=0.0, end=1.0, text="uno"),
            TranscriptSegment(start=1.0, end=2.0, text="dos"),
        ],
    )
    assert len(t.segments) == 2


def test_transcript_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        Transcript(
            call_id=uuid4(),
            model="faster-whisper:tiny",
            created_at=datetime.now(tz=UTC),
            unexpected="boom",
        )


def test_transcript_roundtrips_through_json() -> None:
    original = Transcript(
        call_id=uuid4(),
        model="faster-whisper:tiny",
        created_at=datetime.now(tz=UTC),
        segments=[TranscriptSegment(start=0.0, end=1.0, text="hola", confidence=0.9)],
    )
    rebuilt = Transcript.model_validate_json(original.model_dump_json())
    assert rebuilt.call_id == original.call_id
    assert len(rebuilt.segments) == 1
    assert rebuilt.segments[0].confidence == 0.9
