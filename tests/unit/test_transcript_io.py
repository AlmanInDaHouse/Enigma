"""Tests para `save_transcript` y `load_transcript` (T-104)."""

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from enigma.config import settings
from enigma.ingest.transcriber import load_transcript, save_transcript
from enigma.models.transcript import Transcript, TranscriptSegment


@pytest.fixture(autouse=True)
def _isolate_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Aísla `data/transcripts/` bajo `tmp_path` por test."""
    monkeypatch.setattr(settings, "enigma_data_path", tmp_path / "data")


def _sample_transcript() -> Transcript:
    return Transcript(
        call_id=uuid4(),
        model="faster-whisper:tiny",
        created_at=datetime.now(tz=UTC),
        segments=[
            TranscriptSegment(start=0.0, end=1.5, text="hola", confidence=0.9),
            TranscriptSegment(start=1.5, end=3.2, text="mundo", confidence=0.85),
        ],
    )


def test_save_creates_json_file_in_canonical_path() -> None:
    t = _sample_transcript()
    path = save_transcript(t)
    expected = settings.enigma_data_path / "transcripts" / f"{t.call_id}.json"
    assert path == expected
    assert path.is_file()


def test_save_creates_parent_dir_if_missing() -> None:
    t = _sample_transcript()
    target_dir = settings.enigma_data_path / "transcripts"
    assert not target_dir.exists()
    save_transcript(t)
    assert target_dir.is_dir()


def test_save_and_load_roundtrip_preserves_data() -> None:
    original = _sample_transcript()
    save_transcript(original)
    loaded = load_transcript(original.call_id)
    assert loaded is not None
    assert loaded.call_id == original.call_id
    assert loaded.model == original.model
    assert len(loaded.segments) == 2
    assert loaded.segments[0].text == "hola"
    assert loaded.segments[0].confidence == 0.9


def test_load_returns_none_when_missing() -> None:
    assert load_transcript(uuid4()) is None


def test_save_overwrites_existing_file() -> None:
    call_id = uuid4()
    first = Transcript(
        call_id=call_id,
        model="faster-whisper:tiny",
        created_at=datetime.now(tz=UTC),
        segments=[TranscriptSegment(start=0.0, end=1.0, text="primero")],
    )
    save_transcript(first)
    second = Transcript(
        call_id=call_id,
        model="faster-whisper:base",
        created_at=datetime.now(tz=UTC),
        segments=[
            TranscriptSegment(start=0.0, end=1.0, text="segundo"),
            TranscriptSegment(start=1.0, end=2.0, text="version"),
        ],
    )
    save_transcript(second)

    loaded = load_transcript(call_id)
    assert loaded is not None
    assert loaded.model == "faster-whisper:base"
    assert len(loaded.segments) == 2
    assert loaded.segments[0].text == "segundo"


def test_saved_json_is_human_readable() -> None:
    """El JSON se guarda con indent=2 para facilitar inspección manual."""
    t = _sample_transcript()
    path = save_transcript(t)
    content = path.read_text(encoding="utf-8")
    assert "\n  " in content  # hay indentación
    assert str(t.call_id) in content
