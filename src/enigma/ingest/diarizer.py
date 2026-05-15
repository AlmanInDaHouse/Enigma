"""Diarización de audio con pyannote.audio (T-103).

`diarize_audio()` devuelve los turnos de habla — quién habla en qué ventana
de tiempo. El pipeline de pyannote es costoso de cargar (descarga modelos de
HuggingFace la primera vez), así que se cachea por proceso vía `lru_cache`.

Requisitos:
- `PYANNOTE_AUTH_TOKEN` en `.env` (token de HuggingFace).
- Haber aceptado las condiciones del modelo `settings.diarization_model`
  (por defecto `pyannote/speaker-diarization-community-1`) en huggingface.co.

La asignación de los hablantes a los segmentos del `Transcript` la hace
`enigma.ingest.transcriber.assign_speakers`.
"""

from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from enigma.config import settings

if TYPE_CHECKING:
    from pyannote.audio import Pipeline


class DiarizationTurn(BaseModel):
    """Un turno de habla: un hablante ocupando la ventana `[start, end]`."""

    model_config = ConfigDict(extra="forbid")

    start: float = Field(..., ge=0.0)
    end: float = Field(..., ge=0.0)
    speaker: str


class DiarizationError(RuntimeError):
    """Fallo al cargar el pipeline pyannote o al diarizar un audio."""


@lru_cache(maxsize=1)
def _get_pipeline(model: str, token: str | None) -> "Pipeline":
    """Carga y cachea el pipeline de diarización pyannote.

    Raises:
        DiarizationError: si pyannote devuelve `None` (token ausente o
            condiciones del modelo no aceptadas en HuggingFace).
    """
    from pyannote.audio import Pipeline

    pipeline = Pipeline.from_pretrained(model, token=token)
    if pipeline is None:
        raise DiarizationError(
            f"pyannote devolvió None al cargar {model!r}. Revisa "
            "PYANNOTE_AUTH_TOKEN y que aceptaste las condiciones del modelo "
            "en huggingface.co.",
        )
    return pipeline


def diarize_audio(audio_path: Path, *, model: str | None = None) -> list[DiarizationTurn]:
    """Diariza un fichero de audio y devuelve los turnos de habla.

    Args:
        audio_path: Audio a diarizar (wav recomendado; otros formatos pueden
            requerir ffmpeg instalado).
        model: Override del checkpoint pyannote. Por defecto
            `settings.diarization_model`.

    Returns:
        Lista de `DiarizationTurn` ordenada por `start`. Vacía si pyannote no
        detecta habla.
    """
    checkpoint = model or settings.diarization_model
    pipeline = _get_pipeline(checkpoint, settings.pyannote_auth_token)

    # pyannote 4.0 devuelve un `DiarizeOutput` con la `Annotation` en
    # `.speaker_diarization`; pyannote 3.x devolvía la `Annotation` directa.
    # El `getattr` cubre ambos casos.
    output = pipeline(str(audio_path))
    annotation = getattr(output, "speaker_diarization", output)

    turns = [
        DiarizationTurn(start=segment.start, end=segment.end, speaker=str(speaker))
        for segment, _track, speaker in annotation.itertracks(yield_label=True)
    ]
    turns.sort(key=lambda turn: turn.start)
    return turns
