"""Extracción de tareas pendientes del corpus → índice `tasks.md` (T-403).

`build_task_index()` recorre todas las llamadas con transcript persistido,
pide al LLM local las tareas pendientes mencionadas en cada una (con su
responsable cuando se identifica) y agrega el resultado en una nota índice
`vault/tasks.md`, agrupada por llamada y en orden cronológico inverso.

Gemelo estructural de `agent/decisions.py` (T-402): mismo flujo recorre-corpus
→ LLM `format=json` → índice MOC en la raíz del Vault. La diferencia es el
modelo de datos — cada tarea lleva un `assignee` opcional — y que se renderiza
como checklist Markdown (`- [ ] ...`).

La fecha de mención de una tarea es la fecha de grabación de su llamada
(`recorded_at`), visible en la cabecera de cada grupo.
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

from enigma.agent.prompts import build_tasks_messages
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

_INDEX_FILENAME = "tasks.md"
"""Nombre fijo del índice de tareas, en la raíz del Vault."""


class TasksError(RuntimeError):
    """No se pudieron extraer las tareas de una llamada."""


class PendingTask(BaseModel):
    """Una tarea pendiente mencionada en una llamada, con su trazabilidad."""

    model_config = ConfigDict(extra="forbid")

    statement: str
    assignee: str | None
    call_id: UUID
    call_title: str
    recorded_at: datetime
    call_index_stem: str


class TaskIndexResult(BaseModel):
    """Resultado de `build_task_index`: las tareas y métricas de la pasada."""

    model_config = ConfigDict(extra="forbid")

    tasks: list[PendingTask]
    calls_scanned: int
    calls_with_tasks: int
    index_path: Path


class _RawTask(BaseModel):
    """Una entrada de tarea tal como la devuelve el LLM."""

    model_config = ConfigDict(extra="ignore")

    statement: str
    assignee: str | None = None


class _TasksPayload(BaseModel):
    """Forma del JSON que devuelve el LLM."""

    model_config = ConfigDict(extra="ignore")

    tasks: list[_RawTask]


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


def _request_tasks(messages: list[dict[str, str]], *, model: str) -> list[_RawTask]:
    """Pide las tareas al LLM con `format=json` y las valida (con reintentos).

    Raises:
        TasksError: si tras `MAX_LLM_RETRIES` no hay JSON validable.
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
            return _TasksPayload.model_validate_json(content).tasks
        except (json.JSONDecodeError, ValidationError, ollama.ResponseError, KeyError) as exc:
            last_error = exc
            continue
    raise TasksError(
        f"El LLM no produjo tareas válidas tras {MAX_LLM_RETRIES} intentos",
    ) from last_error


def extract_tasks_from_call(
    call: Call,
    transcript: Transcript,
    *,
    model: str | None = None,
) -> list[PendingTask]:
    """Extrae las tareas pendientes de una llamada a partir de su transcript.

    Devuelve una lista (posiblemente vacía) de `PendingTask`. Una transcripción
    sin texto produce `[]` sin llamar al LLM.

    Raises:
        TasksError: si el LLM falla al producir JSON válido.
    """
    transcript_text = _join_transcript(transcript)
    if not transcript_text.strip():
        return []

    messages = build_tasks_messages(
        transcript_text,
        call_title=call.title or "Llamada sin título",
        language=call.language,
    )
    raw_tasks = _request_tasks(messages, model=model or settings.ollama_llm_model)

    stem = call_index_filename(call)[:-3]  # sin `.md`
    tasks: list[PendingTask] = []
    for raw in raw_tasks:
        if not raw.statement.strip():
            continue
        assignee = raw.assignee.strip() if raw.assignee and raw.assignee.strip() else None
        tasks.append(
            PendingTask(
                statement=raw.statement,
                assignee=assignee,
                call_id=call.id,
                call_title=call.title or "Llamada sin título",
                recorded_at=call.recorded_at,
                call_index_stem=stem,
            )
        )
    return tasks


def _render_task_line(task: PendingTask) -> str:
    """Renderiza una tarea como ítem de checklist Markdown."""
    line = f"- [ ] {task.statement}"
    if task.assignee:
        line += f" — _{task.assignee}_"
    return line


def render_tasks_markdown(tasks: list[PendingTask]) -> str:
    """Renderiza el índice `tasks.md`: tareas agrupadas por llamada.

    Las llamadas se ordenan cronológicamente inverso (la más reciente arriba);
    dentro de cada llamada se conserva el orden en que el LLM las devolvió.
    Cada tarea es un checkbox Markdown con el responsable cuando se conoce.
    """
    frontmatter = {
        "type": "task-index",
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "task_count": len(tasks),
    }
    fm_block = yaml.safe_dump(
        frontmatter,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip()

    if not tasks:
        body = "_No hay tareas pendientes registradas._"
        return f"---\n{fm_block}\n---\n\n# Tareas pendientes\n\n{body}\n"

    groups: dict[UUID, list[PendingTask]] = {}
    for task in tasks:
        groups.setdefault(task.call_id, []).append(task)
    ordered = sorted(groups.values(), key=lambda group: group[0].recorded_at, reverse=True)

    sections: list[str] = []
    for group in ordered:
        head = group[0]
        date_str = head.recorded_at.strftime("%Y-%m-%d")
        items = "\n".join(_render_task_line(task) for task in group)
        sections.append(
            f"## {date_str} · [[{head.call_index_stem}|{head.call_title}]]\n\n{items}",
        )

    body = "\n\n".join(sections)
    return f"---\n{fm_block}\n---\n\n# Tareas pendientes\n\n{body}\n"


def write_tasks_index(
    tasks: list[PendingTask],
    *,
    vault_path: Path | None = None,
) -> Path:
    """Persiste `tasks.md` en la raíz del Vault. Idempotente (filename fijo)."""
    root = vault_path if vault_path is not None else settings.enigma_vault_path
    root.mkdir(parents=True, exist_ok=True)
    target = root / _INDEX_FILENAME
    target.write_text(render_tasks_markdown(tasks), encoding="utf-8")
    return target


def build_task_index(
    *,
    model: str | None = None,
    vault_path: Path | None = None,
) -> TaskIndexResult:
    """Recorre el corpus, extrae tareas pendientes y reescribe `vault/tasks.md`.

    Las llamadas sin transcript persistido se saltan. Si la extracción de una
    llamada falla (LLM), esa llamada se omite con un warning — un fallo
    puntual no debe impedir construir el índice del resto.

    Returns:
        `TaskIndexResult` con las tareas agregadas y métricas.
    """
    with get_connection() as conn:
        all_calls = calls_db.list_calls(conn)

    tasks: list[PendingTask] = []
    calls_scanned = 0
    calls_with_tasks = 0

    for call in all_calls:
        transcript = load_transcript(call.id)
        if transcript is None:
            continue
        calls_scanned += 1
        try:
            call_tasks = extract_tasks_from_call(call, transcript, model=model)
        except TasksError:
            _log.warning("Extracción de tareas falló para la llamada %s; se omite", call.id)
            continue
        if call_tasks:
            calls_with_tasks += 1
        tasks.extend(call_tasks)

    index_path = write_tasks_index(tasks, vault_path=vault_path)
    _log.info(
        "Índice de tareas: %d tareas de %d/%d llamadas → %s",
        len(tasks),
        calls_with_tasks,
        calls_scanned,
        index_path,
    )
    return TaskIndexResult(
        tasks=tasks,
        calls_scanned=calls_scanned,
        calls_with_tasks=calls_with_tasks,
        index_path=index_path,
    )
