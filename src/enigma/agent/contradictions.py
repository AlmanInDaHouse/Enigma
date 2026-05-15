"""Detección de contradicciones entre notas → índice `contradictions.md` (T-404).

Una contradicción es un par de notas que afirman algo opuesto sobre la misma
entidad. Comparar las N²/2 parejas con el LLM es inviable, así que los pares
**candidatos** se generan por proximidad semántica: para cada nota, sus top-k
vecinos en Qdrant (mismo patrón que la detección de wikilinks de T-205). Solo
esos pares — deduplicados — pasan por el juicio del LLM. Coste: O(N·k)
llamadas LLM en vez de O(N²).

`build_contradiction_index()` agrega las contradicciones confirmadas en una
nota índice `vault/contradictions.md` (MOC en la raíz del Vault, regenerable).
Requiere el Vault indexado en Qdrant; si la colección está vacía no hay
candidatos y el índice sale vacío, sin error.
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

from enigma.agent.prompts import build_contradiction_messages
from enigma.config import settings
from enigma.models.note import Note
from enigma.vault.reader import load_all_notes
from enigma.vault.writer import note_stem
from enigma.vector.embedder import embed_note
from enigma.vector.qdrant_client import search

_log = logging.getLogger(__name__)

MAX_LLM_RETRIES = 3
"""Reintentos cuando el LLM no devuelve JSON parseable/validable."""

_INDEX_FILENAME = "contradictions.md"
"""Nombre fijo del índice de contradicciones, en la raíz del Vault."""


class ContradictionError(RuntimeError):
    """El LLM falló al juzgar una pareja de notas."""


class Contradiction(BaseModel):
    """Una contradicción confirmada entre dos notas."""

    model_config = ConfigDict(extra="forbid")

    note_a_id: UUID
    note_a_title: str
    note_a_stem: str
    note_b_id: UUID
    note_b_title: str
    note_b_stem: str
    explanation: str


class ContradictionIndexResult(BaseModel):
    """Resultado de `build_contradiction_index`: contradicciones y métricas."""

    model_config = ConfigDict(extra="forbid")

    contradictions: list[Contradiction]
    notes_scanned: int
    pairs_evaluated: int
    index_path: Path


class _Verdict(BaseModel):
    """Forma del JSON que devuelve el LLM al juzgar una pareja."""

    model_config = ConfigDict(extra="ignore")

    contradiction: bool
    explanation: str = ""


@lru_cache(maxsize=1)
def _client() -> ollama.Client:
    """Cliente Ollama cacheado, apuntando a `settings.ollama_host`."""
    return ollama.Client(host=settings.ollama_host)


def find_contradiction_candidates(notes: list[Note]) -> set[frozenset[UUID]]:
    """Genera los pares candidatos a contradicción por proximidad semántica.

    Para cada nota embebe su cuerpo, busca sus vecinos en Qdrant y conserva
    los que superan `contradiction_similarity_threshold`. Los pares se
    devuelven como `frozenset` de dos `note_id` — así (A,B) y (B,A) son el
    mismo elemento y no se evalúan dos veces.

    Solo se consideran vecinos que también estén entre las `notes` dadas
    (un punto de Qdrant huérfano, sin fichero en el Vault, se ignora).
    """
    known_ids = {note.id for note in notes}
    candidates: set[frozenset[UUID]] = set()
    for note in notes:
        vector = embed_note(note)
        # +1: la propia nota está indexada y aparecerá en sus vecinos.
        hits = search(vector, top_k=settings.contradiction_top_k + 1)
        for hit in hits:
            if hit.note_id == note.id or hit.note_id not in known_ids:
                continue
            if hit.score < settings.contradiction_similarity_threshold:
                continue
            candidates.add(frozenset({note.id, hit.note_id}))
    return candidates


def _request_verdict(note_a: Note, note_b: Note, *, model: str) -> _Verdict:
    """Pregunta al LLM si dos notas se contradicen (JSON, con reintentos).

    Raises:
        ContradictionError: si tras `MAX_LLM_RETRIES` no hay JSON validable.
    """
    messages = build_contradiction_messages(note_a.title, note_a.body, note_b.title, note_b.body)
    last_error: Exception | None = None
    for _attempt in range(MAX_LLM_RETRIES):
        try:
            response = _client().chat(
                model=model,
                messages=messages,
                format="json",
                options={"temperature": 0.1},
            )
            content = str(response["message"]["content"])
            return _Verdict.model_validate_json(content)
        except (json.JSONDecodeError, ValidationError, ollama.ResponseError, KeyError) as exc:
            last_error = exc
            continue
    raise ContradictionError(
        f"El LLM no produjo un veredicto válido tras {MAX_LLM_RETRIES} intentos",
    ) from last_error


def judge_contradiction(
    note_a: Note,
    note_b: Note,
    *,
    model: str | None = None,
) -> Contradiction | None:
    """Juzga si dos notas se contradicen. Devuelve la `Contradiction` o `None`.

    Raises:
        ContradictionError: si el LLM falla al producir JSON válido.
    """
    verdict = _request_verdict(note_a, note_b, model=model or settings.ollama_llm_model)
    if not verdict.contradiction:
        return None
    return Contradiction(
        note_a_id=note_a.id,
        note_a_title=note_a.title,
        note_a_stem=note_stem(note_a.id, note_a.title),
        note_b_id=note_b.id,
        note_b_title=note_b.title,
        note_b_stem=note_stem(note_b.id, note_b.title),
        explanation=verdict.explanation,
    )


def render_contradictions_markdown(contradictions: list[Contradiction]) -> str:
    """Renderiza el índice `contradictions.md`.

    Cada contradicción enlaza las dos notas implicadas con `[[wikilink]]` y
    muestra la explicación del LLM.
    """
    frontmatter = {
        "type": "contradiction-index",
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "contradiction_count": len(contradictions),
    }
    fm_block = yaml.safe_dump(
        frontmatter,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip()

    if not contradictions:
        body = "_No se han detectado contradicciones._"
        return f"---\n{fm_block}\n---\n\n# Contradicciones\n\n{body}\n"

    sections: list[str] = []
    for item in contradictions:
        link_a = f"[[{item.note_a_stem}|{item.note_a_title}]]"
        link_b = f"[[{item.note_b_stem}|{item.note_b_title}]]"
        sections.append(f"## {link_a} ⇄ {link_b}\n\n{item.explanation}")

    body = "\n\n".join(sections)
    return f"---\n{fm_block}\n---\n\n# Contradicciones\n\n{body}\n"


def write_contradictions_index(
    contradictions: list[Contradiction],
    *,
    vault_path: Path | None = None,
) -> Path:
    """Persiste `contradictions.md` en la raíz del Vault. Idempotente."""
    root = vault_path if vault_path is not None else settings.enigma_vault_path
    root.mkdir(parents=True, exist_ok=True)
    target = root / _INDEX_FILENAME
    target.write_text(render_contradictions_markdown(contradictions), encoding="utf-8")
    return target


def build_contradiction_index(
    *,
    model: str | None = None,
    vault_path: Path | None = None,
) -> ContradictionIndexResult:
    """Detecta contradicciones en el Vault y reescribe `vault/contradictions.md`.

    Genera los pares candidatos por proximidad semántica (Qdrant) y juzga cada
    uno con el LLM. Un fallo del LLM en una pareja se omite con un warning —
    no debe impedir construir el resto del índice.

    Returns:
        `ContradictionIndexResult` con las contradicciones y métricas.
    """
    notes = load_all_notes(vault_path)
    by_id = {note.id: note for note in notes}

    candidates = find_contradiction_candidates(notes)

    contradictions: list[Contradiction] = []
    pairs_evaluated = 0
    for pair in candidates:
        id_a, id_b = sorted(pair, key=str)
        note_a, note_b = by_id[id_a], by_id[id_b]
        pairs_evaluated += 1
        try:
            result = judge_contradiction(note_a, note_b, model=model)
        except ContradictionError:
            _log.warning("Juicio de contradicción falló para el par %s/%s; se omite", id_a, id_b)
            continue
        if result is not None:
            contradictions.append(result)

    index_path = write_contradictions_index(contradictions, vault_path=vault_path)
    _log.info(
        "Índice de contradicciones: %d detectadas de %d pares (%d notas) → %s",
        len(contradictions),
        pairs_evaluated,
        len(notes),
        index_path,
    )
    return ContradictionIndexResult(
        contradictions=contradictions,
        notes_scanned=len(notes),
        pairs_evaluated=pairs_evaluated,
        index_path=index_path,
    )
