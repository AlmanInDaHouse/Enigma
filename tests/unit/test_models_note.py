"""Tests para `enigma.models.note`."""

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from enigma.models.note import Note, NoteSource


def _valid_note_kwargs() -> dict[str, Any]:
    return {
        "id": uuid4(),
        "title": "Estrategia de captación para clubs de padel",
        "body": "Los clubs de padel representan un nicho de alta densidad.",
        "tags": ["estrategia", "padel"],
        "source": NoteSource(
            call_id=uuid4(),
            timestamp_start=412.5,
            timestamp_end=478.2,
            speakers=["Manuel"],
        ),
        "content_hash": "a" * 64,
        "extracted_by": "qwen2.5:7b",
        "created_at": datetime.now(tz=UTC),
    }


def test_note_minimal_valid_defaults() -> None:
    n = Note(**_valid_note_kwargs())
    assert n.status == "draft"
    assert n.tags == ["estrategia", "padel"]


def test_note_status_must_match_literal() -> None:
    kw = _valid_note_kwargs()
    kw["status"] = "weird"
    with pytest.raises(ValidationError):
        Note(**kw)


def test_note_content_hash_must_be_64_hex_lowercase() -> None:
    kw = _valid_note_kwargs()
    kw["content_hash"] = "Z" * 64
    with pytest.raises(ValidationError):
        Note(**kw)


def test_note_title_cannot_be_empty() -> None:
    kw = _valid_note_kwargs()
    kw["title"] = ""
    with pytest.raises(ValidationError):
        Note(**kw)


def test_note_body_cannot_be_empty() -> None:
    kw = _valid_note_kwargs()
    kw["body"] = ""
    with pytest.raises(ValidationError):
        Note(**kw)


def test_note_extra_fields_forbidden() -> None:
    kw = _valid_note_kwargs()
    kw["misc"] = "boom"
    with pytest.raises(ValidationError):
        Note(**kw)


def test_note_roundtrips_through_json() -> None:
    original = Note(**_valid_note_kwargs())
    rebuilt = Note.model_validate_json(original.model_dump_json())
    assert rebuilt.id == original.id
    assert rebuilt.source.call_id == original.source.call_id
    assert rebuilt.source.speakers == ["Manuel"]


def test_note_source_rejects_negative_timestamps() -> None:
    with pytest.raises(ValidationError):
        NoteSource(
            call_id=uuid4(),
            timestamp_start=-1.0,
            timestamp_end=0.5,
        )


def test_note_source_speakers_defaults_to_empty_list() -> None:
    src = NoteSource(call_id=uuid4(), timestamp_start=0.0, timestamp_end=1.0)
    assert src.speakers == []
