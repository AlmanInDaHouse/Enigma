"""Wrapper de `faster-whisper` para producir `Transcript` desde un `Call`.

El cache `_get_model` mantiene una sola `WhisperModel` por proceso por
combinación `(model_size, device, compute_type)`. Esto evita pagar el warmup
(~1-3 s en CPU) y la carga de pesos (~75 MB para `tiny`, ~1.5 GB para
`large-v3`) en cada llamada.

`transcribe()` opcionalmente diariza (T-103): si `settings.diarization_enabled`
es `True`, llama a pyannote y asigna el hablante a cada segmento por
solapamiento temporal. Un fallo de diarización NO rompe la transcripción
(RF-03 es *Should*, no *Must*) — se registra un warning y se devuelve el
transcript con `speaker=None`.
"""

import logging
import math
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID

from enigma.config import settings
from enigma.ingest.diarizer import DiarizationTurn, diarize_audio
from enigma.models.call import Call
from enigma.models.transcript import Transcript, TranscriptSegment

if TYPE_CHECKING:
    from faster_whisper import WhisperModel

_log = logging.getLogger(__name__)


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


def _dominant_speaker(
    start: float,
    end: float,
    turns: list[DiarizationTurn],
) -> str | None:
    """Devuelve el `speaker` del turno con mayor solapamiento con `[start, end]`.

    `None` si ningún turno solapa con el segmento.
    """
    best_speaker: str | None = None
    best_overlap = 0.0
    for turn in turns:
        overlap = min(end, turn.end) - max(start, turn.start)
        if overlap > best_overlap:
            best_overlap = overlap
            best_speaker = turn.speaker
    return best_speaker


def assign_speakers(transcript: Transcript, turns: list[DiarizationTurn]) -> Transcript:
    """Asigna a cada segmento del `transcript` el hablante dominante.

    Para cada `TranscriptSegment`, elige el `DiarizationTurn` que más solapa
    temporalmente. Devuelve un `Transcript` nuevo (no muta el original). Si
    `turns` está vacío, devuelve el transcript intacto.
    """
    if not turns:
        return transcript
    new_segments = [
        seg.model_copy(update={"speaker": _dominant_speaker(seg.start, seg.end, turns)})
        for seg in transcript.segments
    ]
    return transcript.model_copy(update={"segments": new_segments})


def transcribe(
    call: Call,
    *,
    model_size: str | None = None,
    diarize: bool | None = None,
) -> Transcript:
    """Transcribe el audio de `call` y devuelve un `Transcript`.

    El primer uso paga la carga del modelo (puede descargarlo de HuggingFace
    si no está en caché local). Llamadas subsiguientes con la misma
    `(model_size, device, compute_type)` reutilizan la instancia.

    Args:
        call: La llamada cuyo audio se transcribe.
        model_size: Override del modelo Whisper (`tiny`, `base`, `small`,
            `medium`, `large-v1/2/3`). Por defecto, `settings.whisper_model`.
        diarize: Si diarizar con pyannote. `None` (default) usa
            `settings.diarization_enabled`. Un fallo de diarización se
            registra como warning y NO rompe la transcripción.

    Returns:
        Un `Transcript` con `segments` ordenados temporalmente. `speaker` se
        rellena si la diarización tuvo éxito; `None` en caso contrario.
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

    transcript = Transcript(
        call_id=call.id,
        model=f"faster-whisper:{size}",
        diarization_model=None,
        language=info.language or call.language,
        segments=segments,
        created_at=datetime.now(tz=UTC),
    )

    should_diarize = settings.diarization_enabled if diarize is None else diarize
    if should_diarize:
        try:
            turns = diarize_audio(call.audio_path)
        except Exception:
            _log.warning("Diarización falló para call %s; sigo sin speakers", call.id)
        else:
            transcript = assign_speakers(transcript, turns)
            transcript = transcript.model_copy(
                update={"diarization_model": settings.diarization_model},
            )

    return transcript


def _transcript_path(call_id: UUID) -> Path:
    """Ruta canónica del JSON para un `call_id` (`data/transcripts/<id>.json`)."""
    return settings.enigma_data_path / "transcripts" / f"{call_id}.json"


def save_transcript(transcript: Transcript) -> Path:
    """Persiste `transcript` como JSON. Idempotente: sobrescribe si existe.

    Returns:
        La ruta absoluta del fichero escrito.
    """
    target = _transcript_path(transcript.call_id)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(transcript.model_dump_json(indent=2), encoding="utf-8")
    return target


def load_transcript(call_id: UUID) -> Transcript | None:
    """Carga el Transcript persistido. Devuelve `None` si no hay fichero."""
    path = _transcript_path(call_id)
    if not path.is_file():
        return None
    return Transcript.model_validate_json(path.read_text(encoding="utf-8"))
