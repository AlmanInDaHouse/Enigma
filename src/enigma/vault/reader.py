"""Lectura de notas del Vault para listados y consultas (T-114).

`list_vault_notes()` recorre `inbox/` y `notes/`, parsea el frontmatter de
cada `.md` y devuelve `NoteSummary`s ordenados por `created_at` descendente.
Ficheros sin frontmatter Enigma válido (p.ej. notas creadas a mano sin los
campos obligatorios) se ignoran silenciosamente.
"""

from datetime import datetime
from pathlib import Path
from uuid import UUID

import frontmatter as fm
from pydantic import BaseModel, ConfigDict

from enigma.config import settings

_DEFAULT_SUBDIRS = ("inbox", "notes")
"""Carpetas del Vault donde viven las notas atómicas."""


class NoteSummary(BaseModel):
    """Vista ligera de una nota: lo necesario para listar sin cargar el cuerpo."""

    model_config = ConfigDict(extra="forbid")

    path: Path
    note_id: UUID
    title: str
    created_at: datetime
    status: str
    tags: list[str]
    call_id: UUID


def read_note_summary(path: Path) -> NoteSummary | None:
    """Lee el frontmatter de un `.md` y devuelve su `NoteSummary`.

    Devuelve `None` si el fichero no parsea o le faltan campos obligatorios
    del frontmatter Enigma (`id`, `title`, `created_at`, `source.call_id`).
    """
    try:
        post = fm.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None

    meta = post.metadata
    source = meta.get("source")
    if not isinstance(source, dict):
        return None

    try:
        return NoteSummary(
            path=path,
            note_id=UUID(str(meta["id"])),
            title=str(meta["title"]),
            created_at=datetime.fromisoformat(str(meta["created_at"])),
            status=str(meta.get("status", "draft")),
            tags=list(meta.get("tags") or []),
            call_id=UUID(str(source["call_id"])),
        )
    except (KeyError, ValueError):
        return None


def list_vault_notes(
    vault_path: Path | None = None,
    *,
    since: datetime | None = None,
    subdirs: tuple[str, ...] = _DEFAULT_SUBDIRS,
) -> list[NoteSummary]:
    """Lista las notas del Vault, opcionalmente filtradas por antigüedad.

    Args:
        vault_path: Raíz del Vault. Default `settings.enigma_vault_path`.
        since: Si se da, solo se devuelven notas con `created_at >= since`.
        subdirs: Subcarpetas a recorrer. Default `("inbox", "notes")`.

    Returns:
        `NoteSummary`s ordenados por `created_at` descendente (más reciente
        primero).
    """
    root = vault_path if vault_path is not None else settings.enigma_vault_path

    summaries: list[NoteSummary] = []
    for subdir in subdirs:
        directory = root / subdir
        if not directory.is_dir():
            continue
        for md_file in directory.glob("*.md"):
            summary = read_note_summary(md_file)
            if summary is None:
                continue
            if since is not None and summary.created_at < since:
                continue
            summaries.append(summary)

    summaries.sort(key=lambda s: s.created_at, reverse=True)
    return summaries
