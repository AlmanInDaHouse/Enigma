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

import yaml
from slugify import slugify

from enigma.config import settings
from enigma.models.call import Call
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


# ── Call index (T-112) ──────────────────────────────────────────────────────


_CALL_TITLE_FALLBACK = "llamada"


def call_index_filename(call: Call) -> str:
    """Filename del índice de una llamada: `{YYYY-MM-DD}-{slug}-{short_id}.md`.

    El `short_id` (8 hex del `call.id`) se incluye para garantizar que dos
    llamadas distintas con misma fecha y mismo título no se pisen, y para
    que reingerir el mismo audio (mismo `call_id` determinístico) produzca
    siempre el mismo nombre — base de la idempotencia (RF-10).
    """
    date_str = call.recorded_at.strftime("%Y-%m-%d")
    slug = slugify(call.title or _CALL_TITLE_FALLBACK, max_length=_MAX_SLUG_LEN, word_boundary=True)
    if not slug:
        slug = _CALL_TITLE_FALLBACK
    short_id = call.id.hex[:SHORT_ID_LEN]
    return f"{date_str}-{slug}-{short_id}.md"


def _call_index_frontmatter(call: Call, note_count: int) -> dict[str, object]:
    """Frontmatter del índice: clasifica el fichero como `type: call`."""
    return {
        "type": "call",
        "call_id": str(call.id),
        "recorded_at": call.recorded_at.isoformat(),
        "duration_seconds": call.duration_seconds,
        "language": call.language,
        "participants": list(call.participants),
        "status": call.status,
        "note_count": note_count,
    }


def render_call_index_markdown(call: Call, notes: list[Note]) -> str:
    """Renderiza la nota índice de una llamada como Markdown.

    Estructura:
        ---
        type: call
        call_id: ...
        recorded_at: ...
        duration_seconds: ...
        language: ...
        participants: [...]
        status: ...
        note_count: N
        ---

        # YYYY-MM-DD — <título o "Llamada sin título">

        Duración: XX.X min · N notas extraídas.

        ## Notas extraídas

        - [[slug-shortid]]
        - [[slug-shortid]]
        ...
    """
    fm_block = yaml.safe_dump(
        _call_index_frontmatter(call, len(notes)),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip()

    date_str = call.recorded_at.strftime("%Y-%m-%d")
    display_title = call.title or "Llamada sin título"
    duration_min = call.duration_seconds / 60.0

    if notes:
        # `note_filename(...)[:-3]` quita el `.md` para formar el wikilink Obsidian.
        note_links = "\n".join(f"- [[{note_filename(n)[:-3]}]]" for n in notes)
    else:
        note_links = "_No se extrajeron notas._"

    return (
        f"---\n{fm_block}\n---\n\n"
        f"# {date_str} — {display_title}\n\n"
        f"Duración: {duration_min:.1f} min · {len(notes)} notas extraídas.\n\n"
        f"## Notas extraídas\n\n"
        f"{note_links}\n"
    )


def write_call_index(
    call: Call,
    notes: list[Note],
    *,
    vault_path: Path | None = None,
) -> Path:
    """Persiste la nota índice de la llamada en `<vault>/calls/` (T-112).

    Idempotente: el filename es función pura de `(recorded_at_date,
    title, call_id_short)`, así que reingerir produce el mismo path
    y el contenido se sobrescribe.
    """
    root = vault_path if vault_path is not None else settings.enigma_vault_path
    calls_dir = root / "calls"
    calls_dir.mkdir(parents=True, exist_ok=True)
    target = calls_dir / call_index_filename(call)
    target.write_text(render_call_index_markdown(call, notes), encoding="utf-8")
    return target
