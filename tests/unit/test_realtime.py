"""Tests para `enigma.realtime` (Fase 6 — W1): hub WebSocket + chat."""

from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from enigma.config import settings
from enigma.realtime import ConnectionManager, recent_messages, store_chat

# ── ConnectionManager ───────────────────────────────────────────────────────


async def test_register_adds_to_online() -> None:
    cm = ConnectionManager()
    await cm.register(AsyncMock(), "Ana")
    await cm.register(AsyncMock(), "Beto")
    assert cm.online() == ["Ana", "Beto"]


async def test_register_broadcasts_presence() -> None:
    cm = ConnectionManager()
    ws = AsyncMock()
    await cm.register(ws, "Ana")
    payload = ws.send_json.call_args.args[0]
    assert payload["type"] == "presence"
    assert payload["users"] == ["Ana"]


async def test_unregister_removes_from_online() -> None:
    cm = ConnectionManager()
    ws = AsyncMock()
    await cm.register(ws, "Ana")
    await cm.unregister(ws)
    assert cm.online() == []


async def test_broadcast_reaches_all_connections() -> None:
    cm = ConnectionManager()
    ws_a, ws_b = AsyncMock(), AsyncMock()
    await cm.register(ws_a, "Ana")
    await cm.register(ws_b, "Beto")
    await cm.broadcast({"type": "chat", "message": "x"})
    assert ws_a.send_json.call_args.args[0] == {"type": "chat", "message": "x"}
    assert ws_b.send_json.call_args.args[0] == {"type": "chat", "message": "x"}


async def test_broadcast_drops_dead_connections() -> None:
    cm = ConnectionManager()
    healthy = AsyncMock()
    dead = AsyncMock()
    dead.send_json.side_effect = ConnectionError("socket cerrado")
    await cm.register(healthy, "Ana")
    await cm.register(dead, "Beto")
    await cm.broadcast({"type": "ping"})
    assert cm.online() == ["Ana"]  # la conexión muerta se descartó


# ── señalización de llamadas (W2) ───────────────────────────────────────────


def _payloads(ws: AsyncMock) -> list[dict]:
    """Todos los payloads enviados por un websocket falso."""
    return [call.args[0] for call in ws.send_json.call_args_list]


async def test_register_returns_peer_id() -> None:
    cm = ConnectionManager()
    peer_id = await cm.register(AsyncMock(), "Ana")
    assert isinstance(peer_id, str)
    assert peer_id


async def test_join_call_sends_roster_and_broadcasts() -> None:
    cm = ConnectionManager()
    ws_a, ws_b = AsyncMock(), AsyncMock()
    await cm.register(ws_a, "Ana")
    peer_b = await cm.register(ws_b, "Beto")

    await cm.join_call(ws_b)

    roster = next(p for p in _payloads(ws_b) if p["type"] == "call-roster")
    assert roster["peers"] == []  # nadie más en la llamada todavía
    joined = next(p for p in _payloads(ws_a) if p["type"] == "call-joined")
    assert joined["peer_id"] == peer_b
    assert joined["name"] == "Beto"
    assert cm.call_members() == [{"peer_id": peer_b, "name": "Beto"}]


async def test_join_call_roster_lists_existing_members() -> None:
    cm = ConnectionManager()
    ws_a, ws_b = AsyncMock(), AsyncMock()
    peer_a = await cm.register(ws_a, "Ana")
    await cm.register(ws_b, "Beto")
    await cm.join_call(ws_a)
    await cm.join_call(ws_b)
    roster = next(p for p in _payloads(ws_b) if p["type"] == "call-roster")
    assert roster["peers"] == [{"peer_id": peer_a, "name": "Ana"}]


async def test_leave_call_broadcasts_left() -> None:
    cm = ConnectionManager()
    ws_a = AsyncMock()
    peer_a = await cm.register(ws_a, "Ana")
    await cm.join_call(ws_a)
    await cm.leave_call(ws_a)
    assert {"type": "call-left", "peer_id": peer_a} in _payloads(ws_a)
    assert cm.call_members() == []


async def test_unregister_in_call_broadcasts_left() -> None:
    cm = ConnectionManager()
    ws_a, ws_b = AsyncMock(), AsyncMock()
    peer_a = await cm.register(ws_a, "Ana")
    await cm.register(ws_b, "Beto")
    await cm.join_call(ws_a)
    await cm.unregister(ws_a)
    assert {"type": "call-left", "peer_id": peer_a} in _payloads(ws_b)


async def test_relay_signal_routes_to_target() -> None:
    cm = ConnectionManager()
    ws_a, ws_b = AsyncMock(), AsyncMock()
    peer_a = await cm.register(ws_a, "Ana")
    peer_b = await cm.register(ws_b, "Beto")
    await cm.relay_signal(ws_a, peer_b, {"sdp": "oferta"})
    signal = next(p for p in _payloads(ws_b) if p["type"] == "signal")
    assert signal["from"] == peer_a
    assert signal["data"] == {"sdp": "oferta"}


async def test_send_to_unknown_peer_returns_false() -> None:
    cm = ConnectionManager()
    await cm.register(AsyncMock(), "Ana")
    assert await cm.send_to("peer-fantasma", {"type": "x"}) is False


# ── store_chat / recent_messages ────────────────────────────────────────────


def test_store_chat_persists_message(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enigma_data_path", tmp_path)
    message = store_chat("Ana", "general", "hola equipo")
    assert message is not None
    assert message.author == "Ana"
    assert message.body == "hola equipo"
    assert [m.id for m in recent_messages()] == [message.id]


def test_store_chat_blank_body_returns_none(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "enigma_data_path", tmp_path)
    assert store_chat("Ana", "general", "   ") is None
    assert recent_messages() == []


def test_store_chat_unknown_channel_falls_to_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "enigma_data_path", tmp_path)
    message = store_chat("Ana", "canal-inventado", "mensaje")
    assert message is not None
    assert message.channel == "general"


def test_store_chat_truncates_long_body(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enigma_data_path", tmp_path)
    message = store_chat("Ana", "general", "x" * 5000)
    assert message is not None
    assert len(message.body) == 4000
