"""Hub de tiempo real para la app de comunicación (Fase 6 — W1 + W2).

Gestiona las conexiones WebSocket del equipo sobre un único `/ws`:

- **Chat + presencia (W1):** registro, quién está en línea, difusión de
  mensajes (persistidos en SQLite vía `db/messages.py`).
- **Señalización de llamadas (W2):** quién está en la llamada y relay de los
  mensajes WebRTC (SDP + ICE) entre pares. Los medios viajan peer-to-peer; el
  servidor solo relaya señalización.

Cada conexión recibe un `peer_id` estable (UUID) — la señalización se enruta
por `peer_id`, no por nombre (que puede repetirse). El estado vive en memoria
(proceso único, equipo ≤6 — CONSTITUTION §7).
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi import WebSocket

from enigma.db import messages as messages_db
from enigma.db.sqlite import get_connection
from enigma.models.message import ChatMessage

_log = logging.getLogger(__name__)

CHANNELS: tuple[str, ...] = ("general", "producto", "random")
"""Canales fijos del equipo. Crear canales al vuelo queda para más adelante."""

DEFAULT_CHANNEL = CHANNELS[0]


@dataclass
class _Client:
    """Estado en memoria de una conexión WebSocket."""

    peer_id: str
    name: str
    in_call: bool = False


class ConnectionManager:
    """Registro en memoria de las conexiones WebSocket activas."""

    def __init__(self) -> None:
        self._clients: dict[WebSocket, _Client] = {}

    async def register(self, websocket: WebSocket, name: str) -> str:
        """Registra una conexión con un nombre. Devuelve su `peer_id`."""
        peer_id = uuid4().hex
        self._clients[websocket] = _Client(peer_id=peer_id, name=name)
        await self.broadcast_presence()
        return peer_id

    async def unregister(self, websocket: WebSocket) -> None:
        """Elimina una conexión; avisa de la salida de la llamada y la presencia."""
        client = self._clients.pop(websocket, None)
        if client is None:
            return
        if client.in_call:
            await self.broadcast({"type": "call-left", "peer_id": client.peer_id})
        await self.broadcast_presence()

    def online(self) -> list[str]:
        """Nombres únicos de las personas conectadas, en orden alfabético."""
        return sorted({client.name for client in self._clients.values()})

    def call_members(self) -> list[dict[str, str]]:
        """`{peer_id, name}` de quienes están en la llamada."""
        return [{"peer_id": c.peer_id, "name": c.name} for c in self._clients.values() if c.in_call]

    async def broadcast(self, payload: dict[str, Any]) -> None:
        """Envía `payload` (JSON) a todas las conexiones; descarta las caídas."""
        dead: list[WebSocket] = []
        for websocket in list(self._clients):
            try:
                await websocket.send_json(payload)
            except Exception:  # conexión caída a mitad de envío
                dead.append(websocket)
        for websocket in dead:
            self._clients.pop(websocket, None)

    async def broadcast_presence(self) -> None:
        """Difunde la lista de personas en línea y el estado de la llamada."""
        await self.broadcast({"type": "presence", "users": self.online()})

    async def send_to(self, peer_id: str, payload: dict[str, Any]) -> bool:
        """Envía `payload` a la conexión con ese `peer_id`. `False` si no existe."""
        for websocket, client in self._clients.items():
            if client.peer_id == peer_id:
                try:
                    await websocket.send_json(payload)
                except Exception:
                    return False
                return True
        return False

    async def join_call(self, websocket: WebSocket) -> None:
        """Marca la conexión como participante de la llamada.

        Envía al recién llegado el roster de los demás participantes (para que
        inicie las conexiones WebRTC) y avisa al resto de su entrada.
        """
        client = self._clients.get(websocket)
        if client is None or client.in_call:
            return
        others = self.call_members()
        client.in_call = True
        await websocket.send_json({"type": "call-roster", "peers": others})
        await self.broadcast(
            {"type": "call-joined", "peer_id": client.peer_id, "name": client.name},
        )

    async def leave_call(self, websocket: WebSocket) -> None:
        """Saca la conexión de la llamada y avisa al resto."""
        client = self._clients.get(websocket)
        if client is None or not client.in_call:
            return
        client.in_call = False
        await self.broadcast({"type": "call-left", "peer_id": client.peer_id})

    async def relay_signal(self, websocket: WebSocket, to_peer_id: str, data: Any) -> None:
        """Relaya un mensaje de señalización WebRTC a un par concreto."""
        sender = self._clients.get(websocket)
        if sender is None:
            return
        await self.send_to(
            to_peer_id,
            {"type": "signal", "from": sender.peer_id, "data": data},
        )


manager = ConnectionManager()
"""Hub singleton del proceso."""


def store_chat(author: str, channel: str, body: str) -> ChatMessage | None:
    """Valida y persiste un mensaje de chat.

    Returns:
        El `ChatMessage` guardado, o `None` si el cuerpo queda vacío tras
        recortar. Un canal desconocido cae al canal por defecto.
    """
    clean_body = body.strip()
    if not clean_body:
        return None
    message = ChatMessage(
        id=uuid4(),
        channel=channel if channel in CHANNELS else DEFAULT_CHANNEL,
        author=author,
        body=clean_body[:4000],
        created_at=datetime.now(tz=UTC),
    )
    with get_connection() as conn:
        messages_db.insert_message(conn, message)
    return message


def recent_messages(limit: int = 60) -> list[ChatMessage]:
    """Últimos mensajes de todos los canales, en orden cronológico."""
    with get_connection() as conn:
        return messages_db.list_recent(conn, limit=limit)
