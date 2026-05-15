"""Métricas del sistema para el dashboard `enigma stats` (T-504, RNF-08).

`gather_stats()` recoge tres bloques de métricas:

- **Corpus:** llamadas y notas acumuladas (de SQLite, el Vault y Qdrant).
- **Actividad:** ritmo reciente — llamadas y notas por día.
- **Salud:** un sondeo *en vivo* de la latencia de los componentes (embed
  con Ollama, disponibilidad de Qdrant). Degrada con gracia si algo está
  caído.

La latencia *de pipeline por llamada* no se mide: el esquema SQLite no guarda
tiempos de proceso. Instrumentarla exigiría un cambio de esquema; queda como
mejora futura. El sondeo de salud cubre la parte de latencia de RNF-08 a
nivel de componente.
"""

import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from enigma.db import calls as calls_db
from enigma.db.sqlite import get_connection
from enigma.models.call import Call
from enigma.vault.reader import NoteSummary, list_vault_notes
from enigma.vector.embedder import embed_text
from enigma.vector.qdrant_client import count as qdrant_count

_ORPHAN_TAG = "orphan"
_ACTIVITY_DAYS = 7
"""Ventana (días) del desglose notas/día del bloque de actividad."""


class CorpusStats(BaseModel):
    """Métricas acumuladas del corpus."""

    model_config = ConfigDict(extra="forbid")

    total_calls: int
    calls_by_status: dict[str, int]
    total_notes: int
    notes_by_status: dict[str, int]
    orphan_notes: int
    qdrant_vectors: int | None
    total_audio_hours: float
    avg_notes_per_call: float


class ActivityStats(BaseModel):
    """Ritmo reciente de ingesta."""

    model_config = ConfigDict(extra="forbid")

    calls_last_7d: int
    calls_last_30d: int
    notes_per_day: dict[str, int]


class HealthProbe(BaseModel):
    """Sondeo en vivo de la latencia/disponibilidad de los componentes."""

    model_config = ConfigDict(extra="forbid")

    qdrant_ok: bool
    ollama_ok: bool
    embed_latency_ms: float | None


class EnigmaStats(BaseModel):
    """Conjunto completo de métricas que muestra `enigma stats`."""

    model_config = ConfigDict(extra="forbid")

    corpus: CorpusStats
    activity: ActivityStats
    health: HealthProbe


def _safe_qdrant_count() -> tuple[int | None, bool]:
    """Cuenta los vectores en Qdrant. `(None, False)` si Qdrant no responde.

    Captura cualquier excepción a propósito: es un sondeo de salud y un fallo
    de cualquier tipo (red, Qdrant caído) debe traducirse a "no disponible".
    """
    try:
        return qdrant_count(), True
    except Exception:
        return None, False


def _safe_embed_probe() -> tuple[float | None, bool]:
    """Cronometra un `embed_text` de prueba. `(None, False)` si Ollama falla.

    Captura cualquier excepción a propósito (ver `_safe_qdrant_count`).
    """
    try:
        start = time.perf_counter()
        embed_text("sonda de latencia de enigma stats")
        elapsed_ms = (time.perf_counter() - start) * 1000.0
        return round(elapsed_ms, 1), True
    except Exception:
        return None, False


def _corpus_stats(
    calls: list[Call],
    notes: list[NoteSummary],
    qdrant_vectors: int | None,
) -> CorpusStats:
    """Calcula las métricas acumuladas del corpus."""
    total_audio_hours = sum(call.duration_seconds for call in calls) / 3600.0
    total_calls = len(calls)
    total_notes = len(notes)
    return CorpusStats(
        total_calls=total_calls,
        calls_by_status=dict(Counter(str(call.status) for call in calls)),
        total_notes=total_notes,
        notes_by_status=dict(Counter(note.status for note in notes)),
        orphan_notes=sum(1 for note in notes if _ORPHAN_TAG in note.tags),
        qdrant_vectors=qdrant_vectors,
        total_audio_hours=round(total_audio_hours, 2),
        avg_notes_per_call=round(total_notes / total_calls, 1) if total_calls else 0.0,
    )


def _activity_stats(calls: list[Call], notes: list[NoteSummary]) -> ActivityStats:
    """Calcula el ritmo reciente de ingesta (ventanas de 7 y 30 días)."""
    now = datetime.now(tz=UTC)
    last_7d = now - timedelta(days=7)
    last_30d = now - timedelta(days=30)

    # Desglose notas/día: una entrada por cada uno de los últimos 7 días,
    # aunque sea 0, para que el dashboard pinte la serie completa.
    per_day: dict[str, int] = {
        (now - timedelta(days=offset)).date().isoformat(): 0 for offset in range(_ACTIVITY_DAYS)
    }
    for note in notes:
        day = note.created_at.date().isoformat()
        if day in per_day:
            per_day[day] += 1

    return ActivityStats(
        calls_last_7d=sum(1 for c in calls if c.ingested_at >= last_7d),
        calls_last_30d=sum(1 for c in calls if c.ingested_at >= last_30d),
        notes_per_day=dict(sorted(per_day.items())),
    )


def _health_probe() -> HealthProbe:
    """Sondea en vivo Qdrant y Ollama."""
    _, qdrant_ok = _safe_qdrant_count()
    embed_latency_ms, ollama_ok = _safe_embed_probe()
    return HealthProbe(
        qdrant_ok=qdrant_ok,
        ollama_ok=ollama_ok,
        embed_latency_ms=embed_latency_ms,
    )


def gather_stats(*, vault_path: Path | None = None) -> EnigmaStats:
    """Recoge todas las métricas del sistema.

    Args:
        vault_path: Raíz del Vault. Default `settings.enigma_vault_path`.

    Returns:
        `EnigmaStats` con los bloques de corpus, actividad y salud.
    """
    with get_connection() as conn:
        calls = calls_db.list_calls(conn)
    notes = list_vault_notes(vault_path)

    qdrant_vectors, _ = _safe_qdrant_count()
    return EnigmaStats(
        corpus=_corpus_stats(calls, notes, qdrant_vectors),
        activity=_activity_stats(calls, notes),
        health=_health_probe(),
    )
