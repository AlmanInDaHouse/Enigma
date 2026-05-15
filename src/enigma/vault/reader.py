"""Lectura de notas del Vault para listados y consultas (T-114).

`list_vault_notes()` recorre `inbox/` y `notes/`, parsea el frontmatter de
cada `.md` y devuelve `NoteSummary`s ordenados por `created_at` descendente.
Ficheros sin frontmatter Enigma válido (p.ej. notas creadas a mano sin los
campos obligatorios) se ignoran silenciosamente.
"""

from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import frontmatter as fm
from pydantic import BaseModel, ConfigDict

from enigma.config import settings
from enigma.models.note import Note

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


def _extract_body(content: str) -> str:
    """Extrae el cuerpo de la nota del contenido Markdown (sin frontmatter).

    `render_note_markdown` (T-109) produce `# {title}\n\n{body}\n\n## Origen…`.
    El cuerpo es lo que va tras el H1 del título y antes de la primera
    sección `##` (Origen, Conexiones, etc.).
    """
    before_sections = content.split("\n## ")[0].strip()
    if before_sections.startswith("# "):
        newline = before_sections.find("\n")
        return before_sections[newline:].strip() if newline != -1 else ""
    return before_sections


def read_note(path: Path) -> Note | None:
    """Lee un `.md` del Vault y reconstruye el `Note` completo (con `body`).

    Devuelve `None` si el fichero no parsea o le faltan campos obligatorios
    del frontmatter Enigma. A diferencia de `read_note_summary`, esta función
    sí carga el cuerpo — necesaria para vectorizar (T-203) y para el RAG.
    """
    try:
        post = fm.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None

    meta = post.metadata
    source = meta.get("source")
    if not isinstance(source, dict):
        return None

    data: dict[str, Any] = {
        "id": meta.get("id"),
        "title": meta.get("title"),
        "body": _extract_body(post.content),
        "tags": list(meta.get("tags") or []),
        "source": {
            "call_id": source.get("call_id"),
            "timestamp_start": source.get("timestamp_start"),
            "timestamp_end": source.get("timestamp_end"),
            "speakers": list(source.get("speakers") or []),
        },
        "content_hash": meta.get("content_hash"),
        "status": meta.get("status", "draft"),
        "extracted_by": meta.get("extracted_by"),
        "created_at": meta.get("created_at"),
    }
    try:
        return Note.model_validate(data)
    except ValueError:
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


def load_notes_by_ids(
    note_ids: set[UUID],
    vault_path: Path | None = None,
    *,
    subdirs: tuple[str, ...] = _DEFAULT_SUBDIRS,
) -> dict[UUID, Note]:
    """Carga las notas del Vault cuyo `id` esté en `note_ids`.

    Hace **una sola pasada** por el Vault (no un lookup por id), así que es
    O(N) una vez en vez de O(k·N). Necesaria para el RAG (T-302): la búsqueda
    semántica devuelve `note_id`s pero el payload Qdrant no trae el cuerpo, y
    el RAG necesita el cuerpo como contexto.

    Args:
        note_ids: Conjunto de identificadores a recuperar.
        vault_path: Raíz del Vault. Default `settings.enigma_vault_path`.
        subdirs: Subcarpetas a recorrer. Default `("inbox", "notes")`.

    Returns:
        Mapa `{note_id: Note}` solo de las notas encontradas **en disco**.
        Un `note_id` indexado en Qdrant pero cuyo fichero ya no existe (o no
        parsea) simplemente no aparece en el resultado.
    """
    if not note_ids:
        return {}

    root = vault_path if vault_path is not None else settings.enigma_vault_path
    found: dict[UUID, Note] = {}
    for subdir in subdirs:
        directory = root / subdir
        if not directory.is_dir():
            continue
        for md_file in directory.glob("*.md"):
            note = read_note(md_file)
            if note is not None and note.id in note_ids:
                found[note.id] = note
            if len(found) == len(note_ids):
                return found
    return found
