"""Tests para `enigma.db.calls` (CRUD sobre la tabla `calls`).

Cada test usa una base SQLite `:memory:` aislada, lo que mantiene la suite
rápida y sin estado entre ejecuciones.
"""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from enigma.db import calls as calls_db
from enigma.db.sqlite import get_connection
from enigma.models.call import Call


def _make_call(content_hash: str | None = None, call_id: UUID | None = None) -> Call:
    return Call(
        id=call_id or uuid4(),
        content_hash=content_hash or ("a" * 64),
        audio_path=Path("/tmp/foo.wav"),
        recorded_at=datetime.now(tz=UTC),
        ingested_at=datetime.now(tz=UTC),
    )


def test_insert_and_get_roundtrip() -> None:
    with get_connection(":memory:") as conn:
        original = _make_call()
        calls_db.insert_call(conn, original)
        retrieved = calls_db.get_call(conn, original.id)
        assert retrieved is not None
        assert retrieved.id == original.id
        assert retrieved.content_hash == original.content_hash
        assert retrieved.status == "pending"


def test_get_call_returns_none_when_missing() -> None:
    with get_connection(":memory:") as conn:
        missing = calls_db.get_call(conn, uuid4())
        assert missing is None


def test_find_by_content_hash_returns_match() -> None:
    with get_connection(":memory:") as conn:
        c = _make_call(content_hash="b" * 64)
        calls_db.insert_call(conn, c)
        found = calls_db.find_by_content_hash(conn, "b" * 64)
        assert found is not None
        assert found.id == c.id


def test_find_by_content_hash_returns_none_when_missing() -> None:
    with get_connection(":memory:") as conn:
        assert calls_db.find_by_content_hash(conn, "f" * 64) is None


def test_unique_content_hash_constraint() -> None:
    """Dos `Call` distintos con el mismo `content_hash` rompen la constraint UNIQUE."""
    with get_connection(":memory:") as conn:
        c1 = _make_call(content_hash="c" * 64)
        c2 = _make_call(content_hash="c" * 64)
        calls_db.insert_call(conn, c1)
        with pytest.raises(sqlite3.IntegrityError):
            calls_db.insert_call(conn, c2)


def test_participants_list_roundtrips_through_json() -> None:
    with get_connection(":memory:") as conn:
        call = Call(
            id=uuid4(),
            content_hash="d" * 64,
            audio_path=Path("/tmp/foo.wav"),
            recorded_at=datetime.now(tz=UTC),
            ingested_at=datetime.now(tz=UTC),
            participants=["Manuel", "Cliente X"],
        )
        calls_db.insert_call(conn, call)
        loaded = calls_db.get_call(conn, call.id)
        assert loaded is not None
        assert loaded.participants == ["Manuel", "Cliente X"]
