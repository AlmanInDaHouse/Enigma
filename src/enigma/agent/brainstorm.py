"""Brainstorming sobre una llamada grabada (T-704).

`brainstorm_call(call_id)` toma el transcript de una llamada y pide al LLM
local que EXPANDA sus ideas — analogías, próximos pasos, preguntas abiertas y
riesgos — en vez de resumir lo dicho. Es lo opuesto al resumen ejecutivo
(T-401): busca lo que la llamada NO dijo pero merece explorarse.

A diferencia de los índices del agente (decisiones, tareas, temas), no escribe
ninguna nota: el resultado se consume en vivo desde la app (`POST
/calls/{id}/brainstorm`). Single-shot sobre el transcript completo.
"""

import json
import logging
from functools import lru_cache
from uuid import UUID

import ollama
from pydantic import BaseModel, ConfigDict, ValidationError

from enigma.agent.prompts import build_brainstorm_messages
from enigma.config import settings
from enigma.db import calls as calls_db
from enigma.db.sqlite import get_connection
from enigma.ingest.transcriber import load_transcript
from enigma.models.transcript import Transcript

_log = logging.getLogger(__name__)

MAX_LLM_RETRIES = 3
"""Reintentos cuando el LLM no devuelve JSON parseable/validable."""


class BrainstormError(RuntimeError):
    """No se pudo generar el brainstorming de una llamada."""


class Brainstorm(BaseModel):
    """Ideas expandidas por el LLM a partir de una llamada grabada."""

    model_config = ConfigDict(extra="forbid")

    call_id: UUID
    analogies: list[str]
    next_steps: list[str]
    open_questions: list[str]
    risks: list[str]


class _BrainstormPayload(BaseModel):
    """Forma del JSON que devuelve el LLM (sin `call_id`, que se añade aparte)."""

    model_config = ConfigDict(extra="ignore")

    analogies: list[str]
    next_steps: list[str]
    open_questions: list[str]
    risks: list[str]


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


def _request_brainstorm(
    messages: list[dict[str, str]],
    *,
    model: str,
) -> _BrainstormPayload:
    """Pide el brainstorming al LLM con `format=json` y lo valida (con reintentos).

    La temperatura es más alta que la de la extracción factual (decisiones,
    tareas): aquí queremos divergencia, no fidelidad literal a lo dicho.

    Raises:
        BrainstormError: si tras `MAX_LLM_RETRIES` no hay JSON validable.
    """
    last_error: Exception | None = None
    for _attempt in range(MAX_LLM_RETRIES):
        try:
            response = _client().chat(
                model=model,
                messages=messages,
                format="json",
                options={"temperature": 0.6},
            )
            content = str(response["message"]["content"])
            return _BrainstormPayload.model_validate_json(content)
        except (json.JSONDecodeError, ValidationError, ollama.ResponseError, KeyError) as exc:
            last_error = exc
            continue
    raise BrainstormError(
        f"El LLM no produjo un brainstorming válido tras {MAX_LLM_RETRIES} intentos",
    ) from last_error


def brainstorm_call(call_id: UUID, *, model: str | None = None) -> Brainstorm:
    """Genera el brainstorming de una llamada a partir de su transcript.

    Args:
        call_id: Identificador de la llamada.
        model: Override del LLM. Default `settings.ollama_llm_model`.

    Returns:
        Un `Brainstorm` con las cuatro categorías de ideas expandidas.

    Raises:
        BrainstormError: si la llamada no existe, no tiene transcript
            persistido, su transcript está vacío, o el LLM falla.
    """
    with get_connection() as conn:
        call = calls_db.get_call(conn, call_id)
    if call is None:
        raise BrainstormError(f"No existe ninguna llamada con id {call_id}")

    transcript = load_transcript(call_id)
    if transcript is None:
        raise BrainstormError(f"La llamada {call_id} no tiene transcripción persistida")

    transcript_text = _join_transcript(transcript)
    if not transcript_text.strip():
        raise BrainstormError(f"La transcripción de la llamada {call_id} está vacía")

    messages = build_brainstorm_messages(
        transcript_text,
        call_title=call.title or "Llamada sin título",
        language=call.language,
    )
    payload = _request_brainstorm(messages, model=model or settings.ollama_llm_model)
    return Brainstorm(
        call_id=call_id,
        analogies=[s.strip() for s in payload.analogies if s.strip()],
        next_steps=[s.strip() for s in payload.next_steps if s.strip()],
        open_questions=[s.strip() for s in payload.open_questions if s.strip()],
        risks=[s.strip() for s in payload.risks if s.strip()],
    )
