"""Wrapper de `faster-whisper` para producir `Transcript` desde un `Call`.

El cache `_get_model` mantiene una sola `WhisperModel` por proceso por
combinación `(model_size, device, compute_type)`. Esto evita pagar el warmup
(~1-3 s en CPU) y la carga de pesos (~75 MB para `tiny`, ~1.5 GB para
`large-v3`) en cada llamada.

T-103 reemplazará `speaker=None` en los segmentos con la salida de pyannote.
"""

import math
from datetime import UTC, datetime
from functools import lru_cache
from typing import TYPE_CHECKING

from enigma.config import settings
from enigma.models.call import Call
from enigma.models.transcript import Transcript, TranscriptSegment

if TYPE_CHECKING:
    from faster_whisper import WhisperModel


def _resolve_device() -> str:
    """Resuelve `WHISPER_DEVICE='auto'` a `'cuda'` (si disponible) o `'cpu'`."""
    requested = settings.whisper_device.lower()
    if requested != "auto":
        return requested
    try:
        import torch
    except ImportError:
        return "cpu"
    return "cuda" if torch.cuda.is_available() else "cpu"


def _resolve_compute_type(device: str) -> str:
    """Resuelve `WHISPER_COMPUTE_TYPE='auto'` al óptimo según `device`."""
    requested = settings.whisper_compute_type.lower()
    if requested != "auto":
        return requested
    return "float16" if device == "cuda" else "int8"


@lru_cache(maxsize=4)
def _get_model(model_size: str, device: str, compute_type: str) -> "WhisperModel":
    """Cachea una `WhisperModel` por `(model_size, device, compute_type)`."""
    from faster_whisper import WhisperModel

    return WhisperModel(model_size, device=device, compute_type=compute_type)


def _confidence_from_logprob(avg_logprob: float | None) -> float | None:
    """Convierte el `avg_logprob` (log-space) en una probabilidad en `[0, 1]`."""
    if avg_logprob is None:
        return None
    return max(0.0, min(1.0, math.exp(avg_logprob)))


def transcribe(call: Call, *, model_size: str | None = None) -> Transcript:
    """Transcribe el audio de `call` y devuelve un `Transcript`.

    El primer uso paga la carga del modelo (puede descargarlo de HuggingFace
    si no está en caché local). Llamadas subsiguientes con la misma
    `(model_size, device, compute_type)` reutilizan la instancia.

    Args:
        call: La llamada cuyo audio se transcribe.
        model_size: Override del modelo Whisper (`tiny`, `base`, `small`,
            `medium`, `large-v1/2/3`). Por defecto, `settings.whisper_model`.

    Returns:
        Un `Transcript` con `segments` ordenados temporalmente. `speaker` queda
        `None` (lo rellena T-103 con pyannote).
    """
    size = model_size or settings.whisper_model
    device = _resolve_device()
    compute_type = _resolve_compute_type(device)

    model = _get_model(size, device, compute_type)
    raw_segments, info = model.transcribe(
        str(call.audio_path),
        language=call.language,
        vad_filter=True,
    )

    segments = [
        TranscriptSegment(
            start=seg.start,
            end=seg.end,
            text=seg.text.strip(),
            speaker=None,
            confidence=_confidence_from_logprob(seg.avg_logprob),
        )
        for seg in raw_segments
    ]

    return Transcript(
        call_id=call.id,
        model=f"faster-whisper:{size}",
        diarization_model=None,
        language=info.language or call.language,
        segments=segments,
        created_at=datetime.now(tz=UTC),
    )
