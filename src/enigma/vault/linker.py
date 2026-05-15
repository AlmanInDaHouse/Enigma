"""Detección de wikilinks entre notas (T-205).

Estrategia (PLAN.md §4.7):
1. Se embebe el cuerpo de la nota.
2. Se buscan en Qdrant las top-k notas más cercanas.
3. Se filtran por `settings.link_similarity_threshold` y se excluye la
   propia nota.
4. Si `settings.link_llm_validation`, un LLM descarta los candidatos cuya
   cercanía sea superficial (comparten palabras pero no idea).

La inyección de los `[[wikilink]]` en el cuerpo de la nota es T-206.
"""

import json
import logging
import re
from functools import lru_cache
from pathlib import Path
from uuid import UUID

import ollama
from pydantic import BaseModel, ConfigDict

from enigma.config import settings
from enigma.models.note import Note
from enigma.vault.reader import list_vault_notes, read_note
from enigma.vault.writer import note_stem, upsert_note
from enigma.vector.embedder import embed_note
from enigma.vector.qdrant_client import search

_log = logging.getLogger(__name__)

_WIKILINK_RE = re.compile(r"\[\[[^\]]+\]\]")
"""Detecta `[[wikilink]]` en el contenido Markdown de una nota."""

_ORPHAN_TAG = "orphan"
"""Tag con el que se marcan las notas sin conexiones (CONSTITUTION §10)."""

_LINK_VALIDATION_SYSTEM = """\
Eres un asistente que decide si dos notas atómicas estilo Zettelkasten deben
enlazarse en el grafo de conocimiento.

Responde EXCLUSIVAMENTE con JSON: {"link": true} o {"link": false}.

Enlaza (true) si las dos notas tratan ideas relacionadas que un lector querría
navegar entre sí. NO enlaces (false) si solo comparten palabras superficiales o
si los temas son demasiado distintos.
"""


class WikilinkSuggestion(BaseModel):
    """Una sugerencia de wikilink desde una nota hacia otra."""

    model_config = ConfigDict(extra="forbid")

    target_note_id: UUID
    target_title: str
    score: float


@lru_cache(maxsize=1)
def _client() -> ollama.Client:
    """Cliente Ollama cacheado para la validación de links."""
    return ollama.Client(host=settings.ollama_host)


def _validate_link_with_llm(source: Note, target_title: str, *, model: str) -> bool:
    """Pregunta al LLM si enlazar `source` → nota titulada `target_title` tiene sentido.

    Un fallo del LLM se interpreta como "no enlazar" (conservador): mejor
    perder un link válido que inyectar uno espurio.
    """
    messages = [
        {"role": "system", "content": _LINK_VALIDATION_SYSTEM},
        {
            "role": "user",
            "content": (
                f"NOTA A (origen)\nTítulo: {source.title}\nCuerpo: {source.body}\n\n"
                f"NOTA B (candidata)\nTítulo: {target_title}\n\n"
                "¿Debe la nota A enlazar hacia la nota B?"
            ),
        },
    ]
    try:
        response = _client().chat(
            model=model,
            messages=messages,
            format="json",
            options={"temperature": 0.1},
        )
        verdict = json.loads(str(response["message"]["content"]))
    except (json.JSONDecodeError, ollama.ResponseError, KeyError):
        _log.warning("Validación LLM del wikilink falló; se descarta el candidato")
        return False
    return bool(verdict.get("link", False))


def suggest_wikilinks(note: Note, *, model: str | None = None) -> list[WikilinkSuggestion]:
    """Sugiere wikilinks desde `note` hacia notas semánticamente cercanas.

    Args:
        note: Nota origen.
        model: Override del LLM de validación. Default `settings.ollama_llm_model`.

    Returns:
        Sugerencias ordenadas por `score` descendente (las más cercanas
        primero). Vacía si no hay candidatos sobre el umbral.
    """
    vector = embed_note(note)
    # +1 candidato extra: la propia nota puede estar indexada y aparecer.
    hits = search(vector, top_k=settings.link_top_k_candidates + 1)

    candidates = [
        hit
        for hit in hits
        if hit.note_id != note.id and hit.score >= settings.link_similarity_threshold
    ][: settings.link_top_k_candidates]

    effective_model = model or settings.ollama_llm_model
    suggestions: list[WikilinkSuggestion] = []
    for hit in candidates:
        title = str(hit.payload.get("title", ""))
        if settings.link_llm_validation and not _validate_link_with_llm(
            note, title, model=effective_model
        ):
            continue
        suggestions.append(
            WikilinkSuggestion(
                target_note_id=hit.note_id,
                target_title=title,
                score=hit.score,
            )
        )
    return suggestions


def format_wikilink(suggestion: WikilinkSuggestion) -> str:
    """Construye el wikilink Obsidian `[[stem|título]]` de una sugerencia.

    El `stem` (filename sin `.md`) es lo que Obsidian resuelve; el título
    se muestra como texto del enlace — legible aunque el filename sea
    `slug-shortid`.
    """
    stem = note_stem(suggestion.target_note_id, suggestion.target_title)
    return f"[[{stem}|{suggestion.target_title}]]"


def apply_wikilinks(
    note: Note,
    suggestions: list[WikilinkSuggestion],
    *,
    vault_dir: Path,
) -> Path:
    """Reescribe la nota en `vault_dir` con una sección `## Conexiones` (T-206).

    Idempotente: re-renderiza la nota completa desde el `Note` + los
    wikilinks, así que reaplicar reemplaza la sección, no la acumula.

    Returns:
        La ruta del fichero reescrito.
    """
    links = [format_wikilink(s) for s in suggestions]
    return upsert_note(note, vault_dir=vault_dir, wikilinks=links)


# ── Detección de notas huérfanas (T-207) ────────────────────────────────────


class OrphanReport(BaseModel):
    """Resultado de una pasada de `mark_orphans`."""

    model_config = ConfigDict(extra="forbid")

    total_notes: int
    orphans: int
    newly_tagged: int


def has_wikilinks(markdown: str) -> bool:
    """`True` si el contenido Markdown contiene al menos un `[[wikilink]]`."""
    return _WIKILINK_RE.search(markdown) is not None


def mark_orphans(vault_path: Path | None = None) -> OrphanReport:
    """Marca con `#orphan` las notas del Vault sin ningún wikilink (CONSTITUTION §10).

    Una nota huérfana es la que no participa en el grafo: ningún
    `[[wikilink]]` en su contenido. Se le añade el tag `orphan` al
    frontmatter para que entre en la cola de revisión.

    Idempotente: una nota que ya tiene el tag `orphan` no se reescribe.

    Returns:
        `OrphanReport` con totales y cuántas se marcaron en esta pasada.
    """
    summaries = list_vault_notes(vault_path)

    orphans = 0
    newly_tagged = 0
    for summary in summaries:
        markdown = summary.path.read_text(encoding="utf-8")
        if has_wikilinks(markdown):
            continue
        orphans += 1
        note = read_note(summary.path)
        if note is None or _ORPHAN_TAG in note.tags:
            continue
        tagged = note.model_copy(update={"tags": [*note.tags, _ORPHAN_TAG]})
        upsert_note(tagged, vault_dir=summary.path.parent)
        newly_tagged += 1

    return OrphanReport(
        total_notes=len(summaries),
        orphans=orphans,
        newly_tagged=newly_tagged,
    )
