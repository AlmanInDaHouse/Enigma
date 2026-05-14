"""Tests para `enigma.models.call`."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from enigma.models.call import Call


def _valid_kwargs() -> dict[str, Any]:
    """Kwargs mínimos válidos para crear un `Call`."""
    return {
        "id": uuid4(),
        "content_hash": "a" * 64,
        "audio_path": Path("/tmp/foo.wav"),
        "recorded_at": datetime.now(tz=UTC),
        "ingested_at": datetime.now(tz=UTC),
    }


def test_call_minimal_valid_has_sensible_defaults() -> None:
    call = Call(**_valid_kwargs())
    assert call.title is None
    assert call.duration_seconds == 0.0
    assert call.language == "es"
    assert call.participants == []
    assert call.status == "pending"
    assert call.error is None


def test_call_content_hash_rejects_wrong_length() -> None:
    kwargs = _valid_kwargs()
    kwargs["content_hash"] = "abc"
    with pytest.raises(ValidationError):
        Call(**kwargs)


def test_call_content_hash_rejects_non_hex() -> None:
    kwargs = _valid_kwargs()
    kwargs["content_hash"] = "Z" * 64  # uppercase + non-hex
    with pytest.raises(ValidationError):
        Call(**kwargs)


def test_call_status_must_match_literal() -> None:
    kwargs = _valid_kwargs()
    kwargs["status"] = "invented_state"
    with pytest.raises(ValidationError):
        Call(**kwargs)


def test_call_extra_fields_forbidden() -> None:
    kwargs = _valid_kwargs()
    kwargs["unknown_field"] = "boom"
    with pytest.raises(ValidationError):
        Call(**kwargs)


def test_call_roundtrips_through_json() -> None:
    """Pydantic dump → load no pierde información."""
    original = Call(**_valid_kwargs())
    data = original.model_dump_json()
    rebuilt = Call.model_validate_json(data)
    assert rebuilt.id == original.id
    assert rebuilt.content_hash == original.content_hash
    assert rebuilt.audio_path == original.audio_path
