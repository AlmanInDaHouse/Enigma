"""Resumen ejecutivo de una llamada (T-401, RF-08).

`summarize_call()` carga el `Call` (SQLite) y su `Transcript` persistido,
pide al LLM local un resumen estructurado (TL;DR + puntos clave + temas) y lo
escribe como nota propia en `vault/calls/`.

La nota-resumen es un fichero separado del índice de llamada (T-112): el
índice lo regenera el pipeline en cada re-ingest, así que inyectar ahí el
resumen lo perdería. El filename es determinista
(`{índice-de-llamada}-summary.md`), de modo que re-resumir sobrescribe sin
duplicar; la nota enlaza al índice con un `[[wikilink]]`.

El resumen se genera con **una sola llamada al LLM** sobre el transcript
completo. Para llamadas que excedan la ventana de contexto del modelo haría
falta un esquema map-reduce — queda como mejora futura (CONSTITUTION §7:
simplicidad primero).
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

from enigma.agent.prompts import build_summary_messages
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


class SummarizationError(RuntimeError):
    """No se pudo generar el resumen de la llamada."""


class CallSummary(BaseModel):
    """Resumen estructurado de una llamada, tal como lo produce el LLM."""

    # `extra="ignore"`: el LLM puede añadir claves de más; no deben romper.
    model_config = ConfigDict(extra="ignore")

    tldr: str
    key_points: list[str]
    topics: list[str]


class SummaryResult(BaseModel):
    """Resultado de `summarize_call`: el resumen y dónde se escribió."""

    model_config = ConfigDict(extra="forbid")

    call: Call
    summary: CallSummary
    summary_path: Path


@lru_cache(maxsize=1)
def _client() -> ollama.Client:
    """Cliente Ollama cacheado, apuntando a `settings.ollama_host`."""
    return ollama.Client(host=settings.ollama_host)


def _join_transcript(transcript: Transcript) -> str:
    """Une los segmentos del transcript en un texto plano para el prompt.

    Prefija cada segmento con su hablante (`[SPEAKER_00] ...`) cuando la
    diarización lo asignó: ayuda al LLM a atribuir puntos a participantes.
    """
    lines: list[str] = []
    for seg in transcript.segments:
        text = seg.text.strip()
        if not text:
            continue
        lines.append(f"[{seg.speaker}] {text}" if seg.speaker else text)
    return "\n".join(lines)


def _request_summary(messages: list[dict[str, str]], *, model: str) -> CallSummary:
    """Pide el resumen al LLM con `format=json` y lo valida (con reintentos).

    Raises:
        SummarizationError: si tras `MAX_LLM_RETRIES` no hay JSON validable.
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
            return CallSummary.model_validate_json(content)
        except (json.JSONDecodeError, ValidationError, ollama.ResponseError, KeyError) as exc:
            last_error = exc
            continue
    raise SummarizationError(
        f"El LLM no produjo un resumen válido tras {MAX_LLM_RETRIES} intentos",
    ) from last_error


def render_summary_markdown(call: Call, summary: CallSummary) -> str:
    """Renderiza la nota-resumen de una llamada como Markdown.

    La nota lleva frontmatter `type: call-summary` y enlaza al índice de la
    llamada (T-112) con un `[[wikilink]]`.
    """
    frontmatter = {
        "type": "call-summary",
        "call_id": str(call.id),
        "recorded_at": call.recorded_at.isoformat(),
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "model": settings.ollama_llm_model,
    }
    fm_block = yaml.safe_dump(
        frontmatter,
        allow_unicode=True,
        sort_keys=False,
        default_flow_style=False,
    ).rstrip()

    date_str = call.recorded_at.strftime("%Y-%m-%d")
    display_title = call.title or "Llamada sin título"
    call_index_link = call_index_filename(call)[:-3]  # sin `.md`

    key_points = (
        "\n".join(f"- {point}" for point in summary.key_points)
        if summary.key_points
        else "_Sin puntos clave identificados._"
    )
    topics = (
        "\n".join(f"- {topic}" for topic in summary.topics)
        if summary.topics
        else "_Sin temas identificados._"
    )

    return (
        f"---\n{fm_block}\n---\n\n"
        f"# Resumen ejecutivo — {date_str} · {display_title}\n\n"
        f"> Llamada: [[{call_index_link}]]\n\n"
        f"## TL;DR\n\n{summary.tldr}\n\n"
        f"## Puntos clave\n\n{key_points}\n\n"
        f"## Temas tratados\n\n{topics}\n"
    )


def _summary_filename(call: Call) -> str:
    """Filename de la nota-resumen: el del índice de llamada + `-summary.md`."""
    return f"{call_index_filename(call)[:-3]}-summary.md"


def write_call_summary(
    call: Call,
    summary: CallSummary,
    *,
    vault_path: Path | None = None,
) -> Path:
    """Persiste la nota-resumen en `<vault>/calls/`. Idempotente (filename fijo)."""
    root = vault_path if vault_path is not None else settings.enigma_vault_path
    calls_dir = root / "calls"
    calls_dir.mkdir(parents=True, exist_ok=True)
    target = calls_dir / _summary_filename(call)
    target.write_text(render_summary_markdown(call, summary), encoding="utf-8")
    return target


def summarize_call(
    call_id: UUID,
    *,
    model: str | None = None,
    vault_path: Path | None = None,
) -> SummaryResult:
    """Genera y persiste el resumen ejecutivo de una llamada.

    Args:
        call_id: Identificador de la llamada a resumir.
        model: Override del LLM. Default `settings.ollama_llm_model`.
        vault_path: Raíz del Vault. Default `settings.enigma_vault_path`.

    Returns:
        `SummaryResult` con el `Call`, el `CallSummary` y el path escrito.

    Raises:
        SummarizationError: si la llamada no existe, no tiene transcript,
            el transcript está vacío, o el LLM falla.
    """
    with get_connection() as conn:
        call = calls_db.get_call(conn, call_id)
    if call is None:
        raise SummarizationError(f"No existe ninguna llamada con id {call_id}")

    transcript = load_transcript(call_id)
    if transcript is None:
        raise SummarizationError(
            f"La llamada {call_id} no tiene transcripción persistida",
        )

    transcript_text = _join_transcript(transcript)
    if not transcript_text.strip():
        raise SummarizationError(
            f"La transcripción de la llamada {call_id} está vacía",
        )

    effective_model = model or settings.ollama_llm_model
    messages = build_summary_messages(
        transcript_text,
        call_title=call.title or "Llamada sin título",
        language=call.language,
    )
    summary = _request_summary(messages, model=effective_model)
    summary_path = write_call_summary(call, summary, vault_path=vault_path)

    _log.info("Resumen de la llamada %s escrito en %s", call_id, summary_path)
    return SummaryResult(call=call, summary=summary, summary_path=summary_path)
