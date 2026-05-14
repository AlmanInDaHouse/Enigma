"""Particiona un `Transcript` en ventanas (chunks) con solapamiento por tokens.

El extractor LLM (T-107) procesa un chunk a la vez. Para que el LLM no pierda
contexto en los bordes y para que dos ideas adyacentes no queden cortadas a
la mitad, cada chunk solapa los últimos `overlap_tokens` con el siguiente.

Conteo de tokens: usamos `tiktoken` con el encoding `cl100k_base` como
**aproximación universal**. No coincide exactamente con el tokenizer de
Llama/Qwen, pero está dentro de ±15% en español y es lo suficientemente
estable para decidir cuándo cortar.

`chunk_transcript()` siempre devuelve al menos una chunk si hay segmentos
(incluso si su token_count > chunk_tokens — un segmento aislado no se trocea
porque eso rompería los timestamps).
"""

from functools import lru_cache

import tiktoken
from pydantic import BaseModel, ConfigDict, Field

from enigma.config import settings
from enigma.models.transcript import Transcript


class TranscriptChunk(BaseModel):
    """Una ventana de la transcripción lista para enviar al LLM."""

    model_config = ConfigDict(extra="forbid")

    text: str
    timestamp_start: float = Field(..., ge=0.0)
    timestamp_end: float = Field(..., ge=0.0)
    segment_start_index: int = Field(..., ge=0, description="Índice del primer segmento incluido.")
    segment_end_index: int = Field(
        ...,
        ge=0,
        description="Índice del último segmento incluido (inclusivo).",
    )
    token_count: int = Field(..., ge=0)


@lru_cache(maxsize=1)
def _encoding() -> tiktoken.Encoding:
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Cuenta tokens usando `cl100k_base` (aproximación universal)."""
    return len(_encoding().encode(text))


def _segment_to_text(speaker: str | None, text: str) -> str:
    """Renderiza un segmento al formato que verá el LLM."""
    if speaker:
        return f"[{speaker}] {text}"
    return text


def chunk_transcript(
    transcript: Transcript,
    *,
    chunk_tokens: int | None = None,
    overlap_tokens: int | None = None,
) -> list[TranscriptChunk]:
    """Divide `transcript.segments` en chunks con solapamiento por tokens.

    Args:
        transcript: Transcript a particionar.
        chunk_tokens: Máximo de tokens por chunk. Default
            `settings.extract_chunk_tokens` (1500).
        overlap_tokens: Tokens que se solapan entre chunks consecutivos.
            Default `settings.extract_chunk_overlap` (200). Debe ser <
            `chunk_tokens`.

    Returns:
        Lista de `TranscriptChunk` ordenados temporalmente. Vacía si el
        transcript no tiene segmentos.

    Raises:
        ValueError: si `overlap_tokens >= chunk_tokens`.
    """
    max_tokens = chunk_tokens if chunk_tokens is not None else settings.extract_chunk_tokens
    overlap = overlap_tokens if overlap_tokens is not None else settings.extract_chunk_overlap
    if overlap >= max_tokens:
        raise ValueError(
            f"overlap_tokens ({overlap}) must be < chunk_tokens ({max_tokens})",
        )

    segments = transcript.segments
    if not segments:
        return []

    # Precomputamos el coste token de cada segmento (una sola pasada).
    segment_texts = [_segment_to_text(seg.speaker, seg.text) for seg in segments]
    segment_tokens = [count_tokens(text) for text in segment_texts]

    chunks: list[TranscriptChunk] = []
    i = 0
    n = len(segments)
    while i < n:
        # Acumular segmentos desde i mientras quepan.
        running_tokens = 0
        j = i
        while j < n:
            cost = segment_tokens[j]
            # Aceptamos siempre al menos un segmento, aunque supere max_tokens.
            if j > i and running_tokens + cost > max_tokens:
                break
            running_tokens += cost
            j += 1

        # j es el primer índice NO incluido en el chunk; el último incluido es j-1.
        last_included = j - 1

        chunk_text = "\n".join(segment_texts[i:j])
        chunks.append(
            TranscriptChunk(
                text=chunk_text,
                timestamp_start=segments[i].start,
                timestamp_end=segments[last_included].end,
                segment_start_index=i,
                segment_end_index=last_included,
                token_count=running_tokens,
            )
        )

        if j >= n:
            break  # último chunk, no hay overlap pendiente

        # Calcular dónde arranca el próximo chunk: retroceder desde j hasta
        # cubrir ~overlap tokens, pero siempre avanzar al menos 1 segmento.
        next_start = j
        accumulated = 0
        while next_start > i + 1 and accumulated < overlap:
            next_start -= 1
            accumulated += segment_tokens[next_start]
        i = next_start

    return chunks
