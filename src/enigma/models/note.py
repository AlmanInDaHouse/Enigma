"""Modelo Pydantic para una nota atómica del Vault.

Una `Note` es la unidad de conocimiento estilo Zettelkasten: una sola idea,
trazable hasta el segmento original de la llamada. Su `id` es UUIDv5
determinístico para que reextracciones produzcan el mismo identificador y
permitan upsert idempotente en disco (T-110).
"""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

NoteStatus = Literal["draft", "validated", "archived"]


class NoteSource(BaseModel):
    """Trazabilidad: cómo encontrar el origen de una nota en la transcripción."""

    model_config = ConfigDict(extra="forbid")

    call_id: UUID
    timestamp_start: float = Field(..., ge=0.0)
    timestamp_end: float = Field(..., ge=0.0)
    speakers: list[str] = Field(default_factory=list)


class Note(BaseModel):
    """Nota atómica extraída de un transcript por el extractor LLM."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    title: str = Field(..., min_length=1)
    body: str = Field(..., min_length=1)
    tags: list[str] = Field(default_factory=list)
    source: NoteSource
    content_hash: str = Field(
        ...,
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
        description="SHA-256 hex (lowercase) del cuerpo de la nota.",
    )
    status: NoteStatus = "draft"
    extracted_by: str = Field(
        ...,
        description="Identificador del modelo LLM que generó la nota.",
    )
    created_at: datetime
