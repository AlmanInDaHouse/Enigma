"""Hub de tiempo real para la app de comunicación (Fase 6 — W1).

Gestiona las conexiones WebSocket del equipo: registro, presencia (quién está
en línea) y difusión de mensajes de chat. La señalización WebRTC para las
llamadas (W2) se añadirá sobre este mismo hub.

El estado vive en memoria (proceso único, equipo pequeño — CONSTITUTION §7).
Los mensajes de chat sí se persisten en SQLite vía `db/messages.py`.
"""

import logging
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


class ConnectionManager:
    """Registro en memoria de las conexiones WebSocket activas.

    Cada conexión lleva asociado el nombre con el que la persona se presentó.
    """

    def __init__(self) -> None:
        self._clients: dict[WebSocket, str] = {}

    async def register(self, websocket: WebSocket, name: str) -> None:
        """Asocia una conexión con un nombre y avisa de la presencia."""
        self._clients[websocket] = name
        await self.broadcast_presence()

    async def unregister(self, websocket: WebSocket) -> None:
        """Elimina una conexión y actualiza la presencia."""
        if self._clients.pop(websocket, None) is not None:
            await self.broadcast_presence()

    def online(self) -> list[str]:
        """Nombres únicos de las personas conectadas, en orden alfabético."""
        return sorted(set(self._clients.values()))

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
        """Difunde la lista actual de personas en línea."""
        await self.broadcast({"type": "presence", "users": self.online()})


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
