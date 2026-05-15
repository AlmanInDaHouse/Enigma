"""Sugerencias de conexiones no obvias — "modo serendipia" (T-406).

La serendipia es lo opuesto a los wikilinks de T-205: en vez de enlazar notas
muy similares (obvias), busca pares en la **banda de similitud media** — ni
tan cerca que la conexión sea evidente, ni tan lejos que sean ruido. Sobre
esos candidatos, el LLM juzga si unirlas produce una idea nueva y valiosa.

Estrategia de candidatos: para cada nota, sus vecinos en Qdrant cuyo score
caiga en `[serendipity_min_similarity, serendipity_max_similarity)`. Mantener
los pares por debajo del umbral de wikilink aproxima "conexiones nuevas" (no
las que la detección de wikilinks ya habría enlazado).

`build_serendipity_index()` agrega hasta `serendipity_max_suggestions` (5)
conexiones confirmadas en `vault/serendipity.md`. Se regenera con
`enigma serendipity`; pensado para correrse periódicamente.
"""

import json
import logging
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from uuid import UUID

import ollama
import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

from enigma.agent.prompts import build_serendipity_messages
from enigma.config import settings
from enigma.models.note import Note
from enigma.vault.reader import load_all_notes
from enigma.vault.writer import note_stem
from enigma.vector.embedder import embed_note
from enigma.vector.qdrant_client import search

_log = logging.getLogger(__name__)

MAX_LLM_RETRIES = 3
"""Reintentos cuando el LLM no devuelve JSON parseable/validable."""

_INDEX_FILENAME = "serendipity.md"
"""Nombre fijo del índice de serendipia, en la raíz del Vault."""


class SerendipityError(RuntimeError):
    """El LLM falló al juzgar una conexión serendípica."""


class SerendipitySuggestion(BaseModel):
    """Una conexión no obvia confirmada entre dos notas."""

    model_config = ConfigDict(extra="forbid")

    note_a_id: UUID
    note_a_title: str
    note_a_stem: str
    note_b_id: UUID
    note_b_title: str
    note_b_stem: str
    insight: str


class SerendipityResult(BaseModel):
    """Resultado de `build_serendipity_index`: sugerencias y métricas."""

    model_config = ConfigDict(extra="forbid")

    suggestions: list[SerendipitySuggestion]
    notes_scanned: int
    pairs_evaluated: int
    index_path: Path


class _Verdict(BaseModel):
    """Forma del JSON que devuelve el LLM al juzgar una pareja."""

    model_config = ConfigDict(extra="ignore")

    connection: bool
    insight: str = ""


@lru_cache(maxsize=1)
def _client() -> ollama.Client:
    """Cliente Ollama cacheado, apuntando a `settings.ollama_host`."""
    return ollama.Client(host=settings.ollama_host)


def find_serendipity_candidates(notes: list[Note]) -> list[frozenset[UUID]]:
    """Genera los pares candidatos a conexión serendípica.

    Para cada nota se buscan sus vecinos en Qdrant y se conservan los que
    caen en la banda de similitud media `[serendipity_min_similarity,
    serendipity_max_similarity)`. Los pares se deduplican (A-B = B-A) y se
    devuelven en orden determinista para que el recorte a las primeras N
    sugerencias sea reproducible.
    """
    known_ids = {note.id for note in notes}
    low = settings.serendipity_min_similarity
    high = settings.serendipity_max_similarity

    candidates: set[frozenset[UUID]] = set()
    for note in notes:
        hits = search(embed_note(note), top_k=settings.serendipity_pool)
        for hit in hits:
            if hit.note_id == note.id or hit.note_id not in known_ids:
                continue
            if low <= hit.score < high:
                candidates.add(frozenset({note.id, hit.note_id}))

    # Orden determinista: por el par de ids ordenados como strings.
    return sorted(candidates, key=lambda pair: tuple(sorted(map(str, pair))))


def _request_verdict(note_a: Note, note_b: Note, *, model: str) -> _Verdict:
    """Pregunta al LLM si dos notas tienen una conexión no obvia (JSON).

    Raises:
        SerendipityError: si tras `MAX_LLM_RETRIES` no hay JSON validable.
    """
    messages = build_serendipity_messages(note_a.title, note_a.body, note_b.title, note_b.body)
    last_error: Exception | None = None
    for _attempt in range(MAX_LLM_RETRIES):
        try:
            response = _client().chat(
                model=model,
                messages=messages,
                format="json",
                options={"temperature": 0.3},
            )
            content = str(response["message"]["content"])
            return _Verdict.model_validate_json(content)
        except (json.JSONDecodeError, ValidationError, ollama.ResponseError, KeyError) as exc:
            last_error = exc
            continue
    raise SerendipityError(
        f"El LLM no produjo un veredicto válido tras {MAX_LLM_RETRIES} intentos",
    ) from last_error


def judge_serendipity(
    note_a: Note,
    note_b: Note,
    *,
    model: str | None = None,
) -> SerendipitySuggestion | None:
    """Juzga si dos notas tienen una conexión no obvia. Devuelve la sugerencia o `None`.

    Raises:
        SerendipityError: si el LLM falla al producir JSON válido.
    """
    verdict = _request_verdict(note_a, note_b, model=model or settings.ollama_llm_model)
    if not verdict.connection:
        return None
    return SerendipitySuggestion(
        note_a_id=note_a.id,
        note_a_title=note_a.title,
        note_a_stem=note_stem(note_a.id, note_a.title),
        note_b_id=note_b.id,
        note_b_title=note_b.title,
        note_b_stem=note_stem(note_b.id, note_b.title),
        insight=verdict.insight,
    )


def render_serendipity_markdown(suggestions: list[SerendipitySuggestion]) -> str:
    """Renderiza el índice `serendipity.md`.

    Cada sugerencia enlaza las dos notas con `[[wikilink]]` y muestra el
    *insight* que surge al conectarlas.
    """
    frontmatter = {
        "type": "serendipity-index",
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "suggestion_count": len(suggestions),
    }
    fm_block = yaml.safe_dump(
        frontmatter,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip()

    if not suggestions:
        body = "_No se han encontrado conexiones no obvias._"
        return f"---\n{fm_block}\n---\n\n# Conexiones serendípicas\n\n{body}\n"

    sections: list[str] = []
    for item in suggestions:
        link_a = f"[[{item.note_a_stem}|{item.note_a_title}]]"
        link_b = f"[[{item.note_b_stem}|{item.note_b_title}]]"
        sections.append(f"## {link_a} ✦ {link_b}\n\n{item.insight}")

    body = "\n\n".join(sections)
    return f"---\n{fm_block}\n---\n\n# Conexiones serendípicas\n\n{body}\n"


def write_serendipity_index(
    suggestions: list[SerendipitySuggestion],
    *,
    vault_path: Path | None = None,
) -> Path:
    """Persiste `serendipity.md` en la raíz del Vault. Idempotente."""
    root = vault_path if vault_path is not None else settings.enigma_vault_path
    root.mkdir(parents=True, exist_ok=True)
    target = root / _INDEX_FILENAME
    target.write_text(render_serendipity_markdown(suggestions), encoding="utf-8")
    return target


def build_serendipity_index(
    *,
    model: str | None = None,
    vault_path: Path | None = None,
) -> SerendipityResult:
    """Busca conexiones no obvias en el Vault y reescribe `vault/serendipity.md`.

    Recorre los pares candidatos de la banda de similitud media y se detiene al
    confirmar `serendipity_max_suggestions` conexiones. Un fallo del LLM en una
    pareja se omite con un warning.

    Returns:
        `SerendipityResult` con las sugerencias y métricas de la pasada.
    """
    notes = load_all_notes(vault_path)
    by_id = {note.id: note for note in notes}
    candidates = find_serendipity_candidates(notes)

    suggestions: list[SerendipitySuggestion] = []
    pairs_evaluated = 0
    for pair in candidates:
        if len(suggestions) >= settings.serendipity_max_suggestions:
            break
        id_a, id_b = sorted(pair, key=str)
        pairs_evaluated += 1
        try:
            suggestion = judge_serendipity(by_id[id_a], by_id[id_b], model=model)
        except SerendipityError:
            _log.warning("Juicio de serendipia falló para el par %s/%s; se omite", id_a, id_b)
            continue
        if suggestion is not None:
            suggestions.append(suggestion)

    index_path = write_serendipity_index(suggestions, vault_path=vault_path)
    _log.info(
        "Índice de serendipia: %d conexiones de %d pares evaluados (%d notas) → %s",
        len(suggestions),
        pairs_evaluated,
        len(notes),
        index_path,
    )
    return SerendipityResult(
        suggestions=suggestions,
        notes_scanned=len(notes),
        pairs_evaluated=pairs_evaluated,
        index_path=index_path,
    )
