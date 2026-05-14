"""Registro de Call en SQLite y copia del audio a `data/audio/`.

Punto de entrada del pipeline. La función pública `register_call` es
**idempotente**: si el mismo fichero (mismo SHA-256) ya está registrado,
devuelve el `Call` existente sin tocar disco ni base de datos.
"""

import hashlib
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path

from enigma.config import settings
from enigma.db import calls as calls_db
from enigma.db.sqlite import get_connection
from enigma.models.call import Call

SUPPORTED_EXTENSIONS = frozenset({".wav", ".mp3", ".m4a", ".ogg"})
"""Extensiones de audio aceptadas (RF-01)."""

# Namespace UUIDv5 arbitrario pero estable para derivar `call_id` del hash.
# Cualquier UUID válido sirve; éste se eligió aleatoriamente y se queda fijo.
_CALL_NAMESPACE = uuid.UUID("6f7c1e5a-3f4e-4b6c-a9d0-7a8e2c1b4d3a")


class UnsupportedAudioFormatError(ValueError):
    """Extensión de fichero fuera de `SUPPORTED_EXTENSIONS`."""


def _sha256_of_file(path: Path, *, chunk: int = 1 << 16) -> str:
    """SHA-256 hexadecimal de un fichero, leído por chunks de 64 KB."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def _audio_duration_seconds(path: Path) -> float:
    """Duración en segundos vía `soundfile`. Devuelve 0.0 si no se puede leer."""
    try:
        import soundfile as sf

        info = sf.info(str(path))
    except Exception:
        return 0.0
    return float(info.frames) / float(info.samplerate)


def register_call(audio_path: Path, *, title: str | None = None) -> Call:
    """Registra una llamada y devuelve su `Call`.

    Comportamiento:
        1. Valida que `audio_path` existe y tiene extensión soportada.
        2. Hashea el fichero y deriva `call_id = uuid5(NAMESPACE, sha256_hex)`.
        3. Si el hash ya está en SQLite, devuelve el Call existente
           (idempotente, RF-10).
        4. Si es nuevo: copia el audio a `data/audio/{call_id}{ext}`,
           extrae `duration_seconds`, e inserta en SQLite con
           `status='pending'`.

    Args:
        audio_path: Fichero de audio fuente (no se mueve, se copia).
        title: Título opcional para la llamada.

    Returns:
        El `Call` registrado (nuevo o preexistente).

    Raises:
        FileNotFoundError: si `audio_path` no existe o no es fichero.
        UnsupportedAudioFormatError: si la extensión no está soportada.
    """
    audio_path = audio_path.resolve()

    if not audio_path.is_file():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    ext = audio_path.suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise UnsupportedAudioFormatError(
            f"Unsupported audio extension {ext!r}. Allowed: {sorted(SUPPORTED_EXTENSIONS)}"
        )

    content_hash = _sha256_of_file(audio_path)
    call_id = uuid.uuid5(_CALL_NAMESPACE, content_hash)

    with get_connection() as conn:
        existing = calls_db.find_by_content_hash(conn, content_hash)
        if existing is not None:
            return existing

        target_path = settings.enigma_data_path / "audio" / f"{call_id}{ext}"
        target_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(audio_path, target_path)

        stat = audio_path.stat()
        recorded_at = datetime.fromtimestamp(stat.st_mtime, tz=UTC)

        call = Call(
            id=call_id,
            content_hash=content_hash,
            title=title,
            audio_path=target_path,
            duration_seconds=_audio_duration_seconds(target_path),
            language=settings.whisper_language,
            recorded_at=recorded_at,
            ingested_at=datetime.now(tz=UTC),
            participants=[],
            status="pending",
            error=None,
        )
        calls_db.insert_call(conn, call)
        return call
