"""Generación de frontmatter YAML y renderizado de la nota Markdown (T-109).

Produce el bloque que Obsidian + pluginds tipo Dataview esperan: un YAML
canónico entre `---` con todos los campos obligatorios definidos en
`data-model.md §3`.

Usamos `yaml.safe_dump` directamente (no `frontmatter.dumps`) para tener
control explícito sobre el orden de keys: queremos `id`, `title` y
`created_at` arriba para que la cabecera del fichero sea legible de un
vistazo.
"""

from typing import Any

import yaml

from enigma.models.note import Note

_KEY_ORDER = (
    "id",
    "title",
    "created_at",
    "source",
    "tags",
    "content_hash",
    "status",
    "extracted_by",
)


def build_frontmatter_dict(note: Note) -> dict[str, Any]:
    """Convierte un `Note` en un dict listo para serializar como YAML.

    Cada UUID y datetime se vuelve string para que `yaml.safe_dump` los
    emita sin tags YAML específicos de Python.
    """
    return {
        "id": str(note.id),
        "title": note.title,
        "created_at": note.created_at.isoformat(),
        "source": {
            "call_id": str(note.source.call_id),
            "timestamp_start": note.source.timestamp_start,
            "timestamp_end": note.source.timestamp_end,
            "speakers": list(note.source.speakers),
        },
        "tags": list(note.tags),
        "content_hash": note.content_hash,
        "status": note.status,
        "extracted_by": note.extracted_by,
    }


def render_frontmatter_yaml(note: Note) -> str:
    """Renderiza el bloque YAML (sin las dos líneas `---` envolventes)."""
    dumped: str = yaml.safe_dump(
        build_frontmatter_dict(note),
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    )
    return dumped


def render_note_markdown(note: Note) -> str:
    """Renderiza la nota completa como Markdown: frontmatter + cuerpo + origen.

    Estructura:
        ---
        <yaml frontmatter>
        ---

        # <title>

        <body>

        ## Origen

        Mencionado entre el segundo X.X y el Y.Y.
    """
    yaml_block = render_frontmatter_yaml(note).rstrip()
    origin = (
        f"Mencionado entre el segundo {note.source.timestamp_start:.1f} "
        f"y el {note.source.timestamp_end:.1f}."
    )
    return f"---\n{yaml_block}\n---\n\n# {note.title}\n\n{note.body}\n\n## Origen\n\n{origin}\n"
