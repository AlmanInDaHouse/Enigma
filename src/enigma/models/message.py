"""Modelo Pydantic para un mensaje de chat (Fase 6 — comunicación).

Un `ChatMessage` es una línea de conversación del equipo dentro de un canal.
Es independiente de las notas y las llamadas: el chat es la capa de
comunicación en vivo sobre la que después actúa el pipeline de Enigma.
"""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ChatMessage(BaseModel):
    """Un mensaje enviado por una persona a un canal del equipo."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    channel: str = Field(..., min_length=1, max_length=40)
    author: str = Field(..., min_length=1, max_length=60)
    body: str = Field(..., min_length=1, max_length=4000)
    created_at: datetime
