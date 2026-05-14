"""Modelo Pydantic para una llamada grabada (Call).

Una `Call` es la entidad raíz del pipeline: representa un fichero de audio
ingresado al sistema. Su `id` se deriva determinísticamente del `content_hash`
(SHA-256 hex del audio), de modo que reingerir el mismo fichero produce el
mismo `id` y permite *upsert* idempotente.
"""

from datetime import datetime
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

CallStatus = Literal["pending", "transcribing", "extracting", "done", "failed"]


class Call(BaseModel):
    """Una llamada grabada ingresada en Enigma."""

    model_config = ConfigDict(extra="forbid", frozen=False)

    id: UUID
    content_hash: str = Field(
        ...,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
        description="SHA-256 hex (lowercase) del fichero de audio.",
    )
    title: str | None = None
    audio_path: Path
    duration_seconds: float = 0.0
    language: str = "es"
    recorded_at: datetime
    ingested_at: datetime
    participants: list[str] = Field(default_factory=list)
    status: CallStatus = "pending"
    error: str | None = None
