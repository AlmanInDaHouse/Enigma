"""Modelos Pydantic para una transcripción con segmentos diarizables.

`Transcript` es la salida del transcriptor (`enigma.ingest.transcriber`).
`TranscriptSegment` es la unidad mínima: una ventana de tiempo con texto y,
opcionalmente, hablante y confianza.

Es un artefacto **derivado** del Call: puede reconstruirse en cualquier
momento desde el audio. Su persistencia en disco (JSON) se gestiona en T-104.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class TranscriptSegment(BaseModel):
    """Una ventana [start, end] de una transcripción."""

    model_config = ConfigDict(extra="forbid")

    start: float = Field(..., ge=0.0, description="Segundo de inicio del segmento.")
    end: float = Field(..., ge=0.0, description="Segundo de fin del segmento.")
    text: str
    speaker: str | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)


class Transcript(BaseModel):
    """Transcripción completa de un `Call`, lista para alimentar al extractor."""

    model_config = ConfigDict(extra="forbid")

    call_id: UUID
    model: str = Field(
        ...,
        description="Identificador del modelo, p.ej. `faster-whisper:large-v3`.",
    )
    diarization_model: str | None = None
    language: str = "es"
    segments: list[TranscriptSegment] = Field(default_factory=list)
    created_at: datetime
