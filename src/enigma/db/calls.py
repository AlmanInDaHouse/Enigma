"""CRUD para la tabla `calls`.

Operaciones thin sobre `sqlite3`: insert, get por id, búsqueda por
`content_hash`. La serialización entre `Call` (Pydantic) y la fila SQLite la
gestiona este módulo, no los módulos de dominio.
"""

import json
import sqlite3
from typing import Any
from uuid import UUID

from enigma.models.call import Call


def insert_call(conn: sqlite3.Connection, call: Call) -> None:
    """INSERTa un Call. Si `content_hash` ya existe lanza `sqlite3.IntegrityError`."""
    conn.execute(
        """
        INSERT INTO calls (
            id, content_hash, title, audio_path, duration, language,
            recorded_at, ingested_at, participants, status, error
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(call.id),
            call.content_hash,
            call.title,
            str(call.audio_path),
            call.duration_seconds,
            call.language,
            call.recorded_at.isoformat(),
            call.ingested_at.isoformat(),
            json.dumps(call.participants),
            call.status,
            call.error,
        ),
    )
    conn.commit()


def _row_to_call(row: sqlite3.Row) -> Call:
    """Convierte una fila SQLite en un `Call` validado por Pydantic."""
    data: dict[str, Any] = {
        "id": row["id"],
        "content_hash": row["content_hash"],
        "title": row["title"],
        "audio_path": row["audio_path"],
        "duration_seconds": row["duration"],
        "language": row["language"],
        "recorded_at": row["recorded_at"],
        "ingested_at": row["ingested_at"],
        "participants": json.loads(row["participants"]),
        "status": row["status"],
        "error": row["error"],
    }
    return Call.model_validate(data)


def get_call(conn: sqlite3.Connection, call_id: UUID) -> Call | None:
    """Recupera un Call por `id`. Devuelve `None` si no existe."""
    cur = conn.execute("SELECT * FROM calls WHERE id = ?", (str(call_id),))
    row = cur.fetchone()
    return _row_to_call(row) if row else None


def find_by_content_hash(conn: sqlite3.Connection, content_hash: str) -> Call | None:
    """Busca un Call por `content_hash` (SHA-256 hex)."""
    cur = conn.execute("SELECT * FROM calls WHERE content_hash = ?", (content_hash,))
    row = cur.fetchone()
    return _row_to_call(row) if row else None
