"""End-to-end pipeline: audio → notas en el Vault (T-113).

Función pública `ingest_audio()`: cose los pasos T-101 → T-112 en una sola
llamada. La CLI (`enigma ingest`) es un wrapper delgado encima.

`on_step` es un callback opcional que recibe un mensaje descriptivo al
arrancar cada fase; lo usa la CLI para imprimir progreso. Tests unit pasan
mocks para todos los pasos costosos.
"""

from collections.abc import Callable
from pathlib import Path
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from enigma.db import calls as calls_db
from enigma.db.sqlite import get_connection
from enigma.extract.extractor import extract_notes_from_transcript
from enigma.ingest.audio import register_call
from enigma.ingest.transcriber import save_transcript, transcribe
from enigma.models.call import Call
from enigma.models.note import Note
from enigma.vault.writer import write_call_index, write_notes_to_inbox


class IngestResult(BaseModel):
    """Resultado de `ingest_audio`: lo que la CLI muestra al usuario."""

    model_config = ConfigDict(extra="forbid")

    call: Call
    transcript_path: Path
    notes: list[Note]
    note_paths: list[Path]
    call_index_path: Path


def _update_status(call_id: UUID, status: str) -> None:
    """Helper: actualiza `Call.status` en SQLite con conexión propia."""
    with get_connection() as conn:
        calls_db.update_status(conn, call_id, status)


def ingest_audio(
    audio_path: Path,
    *,
    title: str | None = None,
    on_step: Callable[[str], None] | None = None,
) -> IngestResult:
    """Procesa un audio end-to-end y devuelve los artefactos producidos.

    Fases (cada una invoca `on_step` si está definido):
        1. `register_call` (T-101) — copia audio + fila SQLite, idempotente.
        2. `transcribe` (T-102) + `save_transcript` (T-104) — JSON en disco.
        3. `extract_notes_from_transcript` (T-107+T-108) — LLM + dedup.
        4. `write_notes_to_inbox` (T-111) + `write_call_index` (T-112).

    `Call.status` recorre `pending → transcribing → extracting → done`.

    Args:
        audio_path: Fichero de audio a procesar.
        title: Título opcional para el Call y su índice.
        on_step: Callback `(message: str) -> None` invocado al inicio de
            cada fase. Útil para el CLI; los tests pueden pasar `None`.

    Returns:
        `IngestResult` con el `Call` actualizado y los paths producidos.
    """

    def step(msg: str) -> None:
        if on_step is not None:
            on_step(msg)

    # 1. Register call
    step("Registrando llamada")
    call = register_call(audio_path, title=title)

    # 2. Transcribe + save
    step("Transcribiendo audio")
    _update_status(call.id, "transcribing")
    transcript = transcribe(call)
    transcript_path = save_transcript(transcript)

    # 3. Extract notes
    step("Extrayendo notas atómicas")
    _update_status(call.id, "extracting")
    notes = extract_notes_from_transcript(transcript)

    # 4. Write to Vault
    step("Persistiendo en el Vault")
    note_paths = write_notes_to_inbox(notes)
    final_call = call.model_copy(update={"status": "done"})
    call_index_path = write_call_index(final_call, notes)

    # 5. Mark done in SQLite
    _update_status(call.id, "done")

    return IngestResult(
        call=final_call,
        transcript_path=transcript_path,
        notes=notes,
        note_paths=note_paths,
        call_index_path=call_index_path,
    )
