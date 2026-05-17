"""Tests para `enigma.db.messages` (Fase 6 — W1)."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from enigma.config import settings
from enigma.db import messages as messages_db
from enigma.db.sqlite import get_connection
from enigma.models.message import ChatMessage


def _msg(
    body: str, *, channel: str = "general", author: str = "Ana", mins_ago: int = 0
) -> ChatMessage:
    return ChatMessage(
        id=uuid4(),
        channel=channel,
        author=author,
        body=body,
        created_at=datetime.now(tz=UTC) - timedelta(minutes=mins_ago),
    )


def test_insert_and_list_roundtrip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enigma_data_path", tmp_path)
    sent = _msg("hola equipo")
    with get_connection() as conn:
        messages_db.insert_message(conn, sent)
    with get_connection() as conn:
        recovered = messages_db.list_recent(conn)
    assert len(recovered) == 1
    assert recovered[0].id == sent.id
    assert recovered[0].body == "hola equipo"
    assert recovered[0].author == "Ana"


def test_list_recent_is_chronological(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enigma_data_path", tmp_path)
    with get_connection() as conn:
        messages_db.insert_message(conn, _msg("primero", mins_ago=10))
        messages_db.insert_message(conn, _msg("segundo", mins_ago=5))
        messages_db.insert_message(conn, _msg("tercero", mins_ago=0))
    with get_connection() as conn:
        bodies = [m.body for m in messages_db.list_recent(conn)]
    assert bodies == ["primero", "segundo", "tercero"]


def test_list_recent_respects_limit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enigma_data_path", tmp_path)
    with get_connection() as conn:
        for i in range(6):
            messages_db.insert_message(conn, _msg(f"m{i}", mins_ago=6 - i))
    with get_connection() as conn:
        recent = messages_db.list_recent(conn, limit=3)
    assert [m.body for m in recent] == ["m3", "m4", "m5"]


def test_list_recent_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enigma_data_path", tmp_path)
    with get_connection() as conn:
        assert messages_db.list_recent(conn) == []
