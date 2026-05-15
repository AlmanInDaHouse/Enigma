"""Idempotent upsert de notas como ficheros Markdown en el Vault (T-110).

El filename canónico es `{slug-del-titulo}-{short_id}.md` donde
`short_id` son los 8 primeros caracteres hex del UUID. La combinación
es única para ≤ 10 000 notas (capacidad de v1 según RNF-05) por
birthday paradox: `10000² / 16⁸ ≈ 2.3·10⁻⁵`.

`upsert_note()` es la única forma de cumplir RF-10 (idempotencia): el
`Note.id` es determinístico (T-107, UUIDv5 de
`call_id + chunk_idx + title`), por lo que reingerir la misma llamada
produce el mismo path y el contenido se sobrescribe sin duplicar.
"""

from pathlib import Path

from slugify import slugify

from enigma.config import settings
from enigma.models.note import Note
from enigma.vault.frontmatter import render_note_markdown

SHORT_ID_LEN = 8
"""Caracteres hex del UUID que entran en el nombre del fichero."""

_FALLBACK_SLUG = "untitled"
"""Slug usado cuando el título se reduce a vacío tras normalizar."""

_MAX_SLUG_LEN = 60
"""Tope para el slug; deja margen para `-<short_id>.md` sin pasar de 80 chars."""


def note_filename(note: Note) -> str:
    """Filename canónico de una nota: `{slug}-{short_id}.md`.

    El nombre es función pura del `Note`: dos notas con el mismo `id` y
    `title` producen el mismo nombre. Esto es lo que hace que
    `upsert_note` sea idempotente.
    """
    slug = slugify(note.title, max_length=_MAX_SLUG_LEN, word_boundary=True)
    if not slug:
        slug = _FALLBACK_SLUG
    short_id = note.id.hex[:SHORT_ID_LEN]
    return f"{slug}-{short_id}.md"


def upsert_note(note: Note, *, vault_dir: Path) -> Path:
    """Escribe (o sobrescribe) la nota en `vault_dir/{note_filename(note)}`.

    Crea `vault_dir` si no existe. Devuelve la ruta del fichero escrito.
    Reescribir el mismo `note.id` con cuerpo distinto reemplaza el contenido
    en el mismo path; no se generan duplicados (RF-10).
    """
    vault_dir.mkdir(parents=True, exist_ok=True)
    target = vault_dir / note_filename(note)
    target.write_text(render_note_markdown(note), encoding="utf-8")
    return target


def write_notes_to_inbox(
    notes: list[Note],
    *,
    vault_path: Path | None = None,
) -> list[Path]:
    """Persiste cada nota en `<vault>/inbox/` vía `upsert_note` (T-111).

    `inbox/` es la carpeta donde aterrizan las notas recién extraídas,
    pendientes de revisión humana. Las notas validadas se mueven luego a
    `notes/` actualizando `status` en su frontmatter (flujo manual en
    Obsidian; ver `docs/architecture.md §5`).

    Args:
        notes: Lista de notas (output de `extract_notes_from_transcript`).
        vault_path: Raíz del Vault. Por defecto `settings.enigma_vault_path`.

    Returns:
        Paths escritos en el mismo orden que `notes`. Lista vacía si `notes`
        está vacía.
    """
    root = vault_path if vault_path is not None else settings.enigma_vault_path
    inbox = root / "inbox"
    return [upsert_note(note, vault_dir=inbox) for note in notes]
