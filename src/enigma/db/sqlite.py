"""Conexión SQLite + inicialización de esquema.

Pensado para single-process, baja concurrencia (6 usuarios). Cada llamada a
`get_connection()` abre una conexión nueva, inicializa el esquema con
`CREATE TABLE IF NOT EXISTS` y la cierra al salir del context manager.

Acepta `:memory:` como `path` para tests aislados.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from enigma.config import settings

CREATE_CALLS_TABLE = """
CREATE TABLE IF NOT EXISTS calls (
    id            TEXT PRIMARY KEY,
    content_hash  TEXT NOT NULL UNIQUE,
    title         TEXT,
    audio_path    TEXT NOT NULL,
    duration      REAL NOT NULL DEFAULT 0.0,
    language      TEXT NOT NULL DEFAULT 'es',
    recorded_at   TEXT NOT NULL,
    ingested_at   TEXT NOT NULL,
    participants  TEXT NOT NULL DEFAULT '[]',
    status        TEXT NOT NULL DEFAULT 'pending',
    error         TEXT
);
"""

CREATE_CALLS_HASH_INDEX = """
CREATE INDEX IF NOT EXISTS idx_calls_content_hash ON calls(content_hash);
"""


def db_path() -> Path:
    """Ruta al fichero SQLite (resuelta cada vez para respetar overrides de settings)."""
    return settings.enigma_data_path / "enigma.db"


def init_schema(conn: sqlite3.Connection) -> None:
    """Crea tablas e índices idempotentemente."""
    conn.execute(CREATE_CALLS_TABLE)
    conn.execute(CREATE_CALLS_HASH_INDEX)
    conn.commit()


@contextmanager
def get_connection(path: Path | str | None = None) -> Iterator[sqlite3.Connection]:
    """Devuelve una conexión SQLite con esquema inicializado.

    Args:
        path: Override opcional. `None` usa `settings.enigma_data_path/enigma.db`.
              Acepta también la cadena `":memory:"` para tests.
    """
    target: Path | str
    target = db_path() if path is None else path

    if isinstance(target, Path):
        target.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(target))
    else:
        conn = sqlite3.connect(target)

    conn.row_factory = sqlite3.Row
    try:
        init_schema(conn)
        yield conn
    finally:
        conn.close()
