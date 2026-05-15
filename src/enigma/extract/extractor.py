"""Orquesta el pipeline `Transcript -> List[Note]` vía LLM local (Ollama).

Para cada `TranscriptChunk` (T-106), construye los mensajes (T-105), llama
al LLM con `format="json"` para forzar salida JSON parseable, valida con
Pydantic y monta un `Note` por entrada del array.

`note_id` se deriva con UUIDv5 de `(call_id, chunk_idx, title)` para que
reextracciones produzcan el mismo identificador y los siguientes pasos
(T-110 file naming, T-111 vault writer) puedan hacer *upsert* idempotente.

El cliente Ollama se cachea a nivel de módulo (`lru_cache`). Las llamadas
malformadas se reintentan hasta `MAX_LLM_RETRIES`. Notas dentro del array
que fallen validación individual se descartan; un solo elemento corrupto
no rompe la extracción entera.
"""

import hashlib
import json
import uuid
from datetime import UTC, datetime
from functools import lru_cache
from typing import Any
from uuid import UUID

import ollama
from pydantic import ValidationError

from enigma.config import settings
from enigma.extract.chunker import TranscriptChunk, chunk_transcript
from enigma.extract.prompts import build_extraction_messages
from enigma.models.note import Note, NoteSource
from enigma.models.transcript import Transcript

# Namespace UUIDv5 estable para derivar `note_id` desde el seed.
_NOTE_NAMESPACE = uuid.UUID("9b8a1c4e-2f5d-4b6c-a9d0-7a8e2c1b4d3a")

MAX_LLM_RETRIES = 3
"""Reintentos máximos cuando el LLM devuelve JSON inválido."""

_DEFAULT_FALLBACK_TAG = "review-needed"
"""Tag que recibe una nota cuando el LLM no devuelve ninguno."""

_WRAPPER_KEYS_TO_UNWRAP = (
    "notes",
    "notas",
    "items",
    "ideas",
    "result",
    "results",
    "data",
)
"""Claves comunes con las que los LLMs envuelven el array; las desempaquetamos."""


class ExtractionError(RuntimeError):
    """El LLM no produjo JSON válido tras `MAX_LLM_RETRIES` intentos."""


@lru_cache(maxsize=1)
def _client() -> ollama.Client:
    """Cliente Ollama cacheado, apuntando a `settings.ollama_host`."""
    return ollama.Client(host=settings.ollama_host)


def _content_hash(text: str) -> str:
    """SHA-256 hex del cuerpo de la nota."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _build_note_id(call_id: UUID, chunk_idx: int, title: str) -> UUID:
    """`note_id = uuid5(NAMESPACE, '<call_id>|<chunk_idx>|<title>')`."""
    seed = f"{call_id}|{chunk_idx}|{title}"
    return uuid.uuid5(_NOTE_NAMESPACE, seed)


def _llm_call_json(messages: list[dict[str, str]], *, model: str) -> str:
    """Invoca `chat` con `format=json` y reintenta hasta `MAX_LLM_RETRIES`.

    Returns:
        Contenido textual del mensaje del asistente (string JSON).

    Raises:
        ExtractionError: si tras todos los reintentos no se obtiene JSON parseable.
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
            json.loads(content)  # valida sintaxis antes de devolverlo
        except (json.JSONDecodeError, ollama.ResponseError, KeyError) as exc:
            last_error = exc
            continue
        else:
            return content
    raise ExtractionError(
        f"LLM failed to produce valid JSON after {MAX_LLM_RETRIES} retries",
    ) from last_error


def _normalize_to_note_list(parsed: object) -> list[dict[str, Any]]:
    """Normaliza la respuesta del LLM a una lista plana de dicts.

    Aunque el system prompt pide un array, los LLMs locales (incluido
    qwen2.5:7b) a veces lo envuelven en un objeto. Aceptamos los shapes
    razonables y rechazamos el resto.

    Acepta:
        - lista plana de dicts (caso ideal).
        - dict con una de las claves de `_WRAPPER_KEYS_TO_UNWRAP` cuyo
          valor sea una lista de dicts.
        - dict que parezca una sola nota (tiene `title` y `body`) —
          se devuelve como `[parsed]`.

    Raises:
        ExtractionError: si el shape no es reconocible.
    """
    if isinstance(parsed, list):
        return [item for item in parsed if isinstance(item, dict)]

    if isinstance(parsed, dict):
        for key in _WRAPPER_KEYS_TO_UNWRAP:
            value = parsed.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        if "title" in parsed and "body" in parsed:
            return [parsed]

    raise ExtractionError(
        f"LLM returned unrecognized JSON shape: {type(parsed).__name__}",
    )


def _raw_note_to_note(
    raw: dict[str, Any],
    *,
    call_id: UUID,
    chunk: TranscriptChunk,
    chunk_idx: int,
    model: str,
    now: datetime,
) -> Note:
    """Convierte una entrada del array JSON en una `Note` validada por Pydantic.

    Raises:
        KeyError | ValidationError: si la entrada es inválida (el caller
            es responsable de descartarla sin romper la extracción global).
    """
    title = raw["title"]
    body = raw["body"]
    tags = raw.get("tags") or [_DEFAULT_FALLBACK_TAG]
    return Note(
        id=_build_note_id(call_id, chunk_idx, title),
        title=title,
        body=body,
        tags=tags,
        source=NoteSource(
            call_id=call_id,
            timestamp_start=float(raw.get("timestamp_start", chunk.timestamp_start)),
            timestamp_end=float(raw.get("timestamp_end", chunk.timestamp_end)),
            speakers=raw.get("speakers") or [],
        ),
        content_hash=_content_hash(body),
        status="draft",
        extracted_by=model,
        created_at=now,
    )


def extract_notes_from_chunk(
    chunk: TranscriptChunk,
    *,
    call_id: UUID,
    chunk_idx: int = 0,
    model: str | None = None,
) -> list[Note]:
    """Extrae notas atómicas de un único chunk vía LLM.

    Las notas malformadas dentro del array se descartan silenciosamente;
    el caller obtiene solo las válidas. Si el LLM falla completamente
    (JSON no parseable tras reintentos), se eleva `ExtractionError`.

    Returns:
        Lista (posiblemente vacía) de `Note`s extraídas.
    """
    effective_model = model or settings.ollama_llm_model
    messages = build_extraction_messages(chunk.text)
    raw_content = _llm_call_json(messages, model=effective_model)

    raw_notes = _normalize_to_note_list(json.loads(raw_content))

    now = datetime.now(tz=UTC)
    notes: list[Note] = []
    for raw in raw_notes:
        try:
            note = _raw_note_to_note(
                raw,
                call_id=call_id,
                chunk=chunk,
                chunk_idx=chunk_idx,
                model=effective_model,
                now=now,
            )
        except (KeyError, ValidationError, TypeError, ValueError):
            continue
        notes.append(note)
    return notes


def extract_notes_from_transcript(
    transcript: Transcript,
    *,
    model: str | None = None,
) -> list[Note]:
    """Extrae notas de un transcript completo: chunkea + recorre + concatena.

    La deduplicación intra-llamada (T-108) se aplica en una pasada posterior;
    aquí solo se concatenan los resultados de cada chunk en orden.
    """
    chunks = chunk_transcript(transcript)
    all_notes: list[Note] = []
    for idx, chunk in enumerate(chunks):
        all_notes.extend(
            extract_notes_from_chunk(
                chunk,
                call_id=transcript.call_id,
                chunk_idx=idx,
                model=model,
            )
        )
    return all_notes
