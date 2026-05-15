"""Extracción de decisiones del corpus → índice `decisions.md` (T-402).

`build_decision_index()` recorre todas las llamadas con transcript persistido,
pide al LLM local las decisiones tomadas en cada una y agrega el resultado en
una nota índice `vault/decisions.md`, agrupada por llamada y en orden
cronológico inverso (lo más reciente arriba).

Es un índice transversal del corpus (tipo MOC), no una nota atómica ni una
nota de llamada — por eso vive en la raíz del Vault. Cada `enigma decisions`
reescribe el fichero entero (idempotente) y re-extrae todo: una llamada al LLM
por llamada del corpus. Para decenas de llamadas el coste es asumible; si el
corpus crece mucho, cabría cachear por `call_id` — mejora futura.

El resumen se pide single-shot sobre el transcript completo (igual que T-401);
la limitación de ventana de contexto para llamadas muy largas es la misma.
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

from enigma.agent.prompts import build_decisions_messages
from enigma.config import settings
from enigma.db import calls as calls_db
from enigma.db.sqlite import get_connection
from enigma.ingest.transcriber import load_transcript
from enigma.models.call import Call
from enigma.models.transcript import Transcript
from enigma.vault.writer import call_index_filename

_log = logging.getLogger(__name__)

MAX_LLM_RETRIES = 3
"""Reintentos cuando el LLM no devuelve JSON parseable/validable."""

_INDEX_FILENAME = "decisions.md"
"""Nombre fijo del índice de decisiones, en la raíz del Vault."""


class DecisionsError(RuntimeError):
    """No se pudieron extraer las decisiones de una llamada."""


class Decision(BaseModel):
    """Una decisión concreta tomada en una llamada, con su trazabilidad."""

    model_config = ConfigDict(extra="forbid")

    statement: str
    call_id: UUID
    call_title: str
    recorded_at: datetime
    call_index_stem: str


class DecisionIndexResult(BaseModel):
    """Resultado de `build_decision_index`: las decisiones y métricas de la pasada."""

    model_config = ConfigDict(extra="forbid")

    decisions: list[Decision]
    calls_scanned: int
    calls_with_decisions: int
    index_path: Path


class _DecisionsPayload(BaseModel):
    """Forma del JSON que devuelve el LLM."""

    model_config = ConfigDict(extra="ignore")

    decisions: list[str]


@lru_cache(maxsize=1)
def _client() -> ollama.Client:
    """Cliente Ollama cacheado, apuntando a `settings.ollama_host`."""
    return ollama.Client(host=settings.ollama_host)


def _join_transcript(transcript: Transcript) -> str:
    """Une los segmentos del transcript en texto plano para el prompt."""
    lines: list[str] = []
    for seg in transcript.segments:
        text = seg.text.strip()
        if not text:
            continue
        lines.append(f"[{seg.speaker}] {text}" if seg.speaker else text)
    return "\n".join(lines)


def _request_decisions(messages: list[dict[str, str]], *, model: str) -> list[str]:
    """Pide las decisiones al LLM con `format=json` y las valida (con reintentos).

    Raises:
        DecisionsError: si tras `MAX_LLM_RETRIES` no hay JSON validable.
    """
    last_error: Exception | None = None
    for _attempt in range(MAX_LLM_RETRIES):
        try:
            response = _client().chat(
                model=model,
                messages=messages,
                format="json",
                options={"temperature": 0.2},
            )
            content = str(response["message"]["content"])
            return _DecisionsPayload.model_validate_json(content).decisions
        except (json.JSONDecodeError, ValidationError, ollama.ResponseError, KeyError) as exc:
            last_error = exc
            continue
    raise DecisionsError(
        f"El LLM no produjo decisiones válidas tras {MAX_LLM_RETRIES} intentos",
    ) from last_error


def extract_decisions_from_call(
    call: Call,
    transcript: Transcript,
    *,
    model: str | None = None,
) -> list[Decision]:
    """Extrae las decisiones de una llamada a partir de su transcript.

    Devuelve una lista (posiblemente vacía) de `Decision`. Una transcripción
    sin texto produce `[]` sin llamar al LLM.

    Raises:
        DecisionsError: si el LLM falla al producir JSON válido.
    """
    transcript_text = _join_transcript(transcript)
    if not transcript_text.strip():
        return []

    messages = build_decisions_messages(
        transcript_text,
        call_title=call.title or "Llamada sin título",
        language=call.language,
    )
    statements = _request_decisions(messages, model=model or settings.ollama_llm_model)

    stem = call_index_filename(call)[:-3]  # sin `.md`
    return [
        Decision(
            statement=statement,
            call_id=call.id,
            call_title=call.title or "Llamada sin título",
            recorded_at=call.recorded_at,
            call_index_stem=stem,
        )
        for statement in statements
        if statement.strip()
    ]


def render_decisions_markdown(decisions: list[Decision]) -> str:
    """Renderiza el índice `decisions.md`: decisiones agrupadas por llamada.

    Las llamadas se ordenan cronológicamente inverso (la más reciente arriba);
    dentro de cada llamada se conserva el orden en que el LLM las devolvió.
    """
    frontmatter = {
        "type": "decision-index",
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "decision_count": len(decisions),
    }
    fm_block = yaml.safe_dump(
        frontmatter,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip()

    if not decisions:
        body = "_No se ha registrado ninguna decisión todavía._"
        return f"---\n{fm_block}\n---\n\n# Decisiones\n\n{body}\n"

    groups: dict[UUID, list[Decision]] = {}
    for decision in decisions:
        groups.setdefault(decision.call_id, []).append(decision)
    ordered = sorted(groups.values(), key=lambda group: group[0].recorded_at, reverse=True)

    sections: list[str] = []
    for group in ordered:
        head = group[0]
        date_str = head.recorded_at.strftime("%Y-%m-%d")
        items = "\n".join(f"- {d.statement}" for d in group)
        sections.append(
            f"## {date_str} · [[{head.call_index_stem}|{head.call_title}]]\n\n{items}",
        )

    body = "\n\n".join(sections)
    return f"---\n{fm_block}\n---\n\n# Decisiones\n\n{body}\n"


def write_decisions_index(
    decisions: list[Decision],
    *,
    vault_path: Path | None = None,
) -> Path:
    """Persiste `decisions.md` en la raíz del Vault. Idempotente (filename fijo)."""
    root = vault_path if vault_path is not None else settings.enigma_vault_path
    root.mkdir(parents=True, exist_ok=True)
    target = root / _INDEX_FILENAME
    target.write_text(render_decisions_markdown(decisions), encoding="utf-8")
    return target


def build_decision_index(
    *,
    model: str | None = None,
    vault_path: Path | None = None,
) -> DecisionIndexResult:
    """Recorre el corpus, extrae decisiones y reescribe `vault/decisions.md`.

    Las llamadas sin transcript persistido se saltan. Si la extracción de una
    llamada falla (LLM), esa llamada se omite con un warning — un fallo
    puntual no debe impedir construir el índice del resto.

    Returns:
        `DecisionIndexResult` con las decisiones agregadas y métricas.
    """
    with get_connection() as conn:
        all_calls = calls_db.list_calls(conn)

    decisions: list[Decision] = []
    calls_scanned = 0
    calls_with_decisions = 0

    for call in all_calls:
        transcript = load_transcript(call.id)
        if transcript is None:
            continue
        calls_scanned += 1
        try:
            call_decisions = extract_decisions_from_call(call, transcript, model=model)
        except DecisionsError:
            _log.warning("Extracción de decisiones falló para la llamada %s; se omite", call.id)
            continue
        if call_decisions:
            calls_with_decisions += 1
        decisions.extend(call_decisions)

    index_path = write_decisions_index(decisions, vault_path=vault_path)
    _log.info(
        "Índice de decisiones: %d decisiones de %d/%d llamadas → %s",
        len(decisions),
        calls_with_decisions,
        calls_scanned,
        index_path,
    )
    return DecisionIndexResult(
        decisions=decisions,
        calls_scanned=calls_scanned,
        calls_with_decisions=calls_with_decisions,
        index_path=index_path,
    )
