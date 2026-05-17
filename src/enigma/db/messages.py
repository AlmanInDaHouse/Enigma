"""CRUD para la tabla `messages` (Fase 6 — comunicación).

Operaciones thin sobre `sqlite3`: insertar un mensaje y leer los más
recientes. La serialización entre `ChatMessage` (Pydantic) y la fila SQLite la
gestiona este módulo.
"""

import sqlite3
from uuid import UUID

from enigma.models.message import ChatMessage


def insert_message(conn: sqlite3.Connection, message: ChatMessage) -> None:
    """INSERTa un mensaje de chat."""
    conn.execute(
        """
        INSERT INTO messages (id, channel, author, body, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            str(message.id),
            message.channel,
            message.author,
            message.body,
            message.created_at.isoformat(),
        ),
    )
    conn.commit()


def _row_to_message(row: sqlite3.Row) -> ChatMessage:
    """Convierte una fila SQLite en un `ChatMessage` validado."""
    return ChatMessage.model_validate(
        {
            "id": UUID(row["id"]),
            "channel": row["channel"],
            "author": row["author"],
            "body": row["body"],
            "created_at": row["created_at"],
        }
    )


def list_recent(conn: sqlite3.Connection, *, limit: int = 60) -> list[ChatMessage]:
    """Devuelve los `limit` mensajes más recientes, en orden cronológico.

    Trae todos los canales: el cliente filtra por el canal activo. Para un
    equipo pequeño el historial reciente cabe holgadamente en memoria.
    """
    cur = conn.execute(
        "SELECT * FROM messages ORDER BY created_at DESC LIMIT ?",
        (limit,),
    )
    rows = cur.fetchall()
    return [_row_to_message(row) for row in reversed(rows)]
