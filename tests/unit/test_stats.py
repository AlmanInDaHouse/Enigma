"""Tests unitarios para `enigma.stats` (T-504).

Mockean SQLite, el Vault, Qdrant y el embedder para verificar el cálculo de
métricas y la degradación del sondeo de salud sin tocar servicios reales.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from enigma.models.call import Call
from enigma.stats import gather_stats
from enigma.vault.reader import NoteSummary


def _call(*, status: str = "done", duration: float = 600.0, days_ago: int = 0) -> Call:
    ingested = datetime.now(tz=UTC) - timedelta(days=days_ago)
    return Call(
        id=uuid4(),
        content_hash=uuid4().hex + uuid4().hex,
        title="Llamada",
        audio_path=Path("/tmp/a.wav"),
        duration_seconds=duration,
        language="es",
        recorded_at=ingested,
        ingested_at=ingested,
        status=status,  # type: ignore[arg-type]
    )


def _note(
    *, status: str = "draft", tags: list[str] | None = None, days_ago: int = 0
) -> NoteSummary:
    return NoteSummary(
        path=Path(f"/vault/inbox/{uuid4().hex}.md"),
        note_id=uuid4(),
        title="Nota",
        created_at=datetime.now(tz=UTC) - timedelta(days=days_ago),
        status=status,
        tags=tags if tags is not None else [],
        call_id=uuid4(),
    )


def _gather(calls: list[Call], notes: list[NoteSummary], **kw: object):
    """Llama a `gather_stats` con SQLite/Vault/Qdrant/Ollama mockeados."""
    qdrant_count = kw.get("qdrant_count", 42)
    embed_ok = kw.get("embed_ok", True)
    qdrant_ok = kw.get("qdrant_ok", True)

    def _count() -> int:
        if not qdrant_ok:
            raise ConnectionError("qdrant down")
        return qdrant_count  # type: ignore[return-value]

    def _embed(_text: str) -> list[float]:
        if not embed_ok:
            raise ConnectionError("ollama down")
        return [0.1] * 768

    with (
        patch("enigma.stats.get_connection"),
        patch("enigma.stats.calls_db.list_calls", return_value=calls),
        patch("enigma.stats.list_vault_notes", return_value=notes),
        patch("enigma.stats.qdrant_count", side_effect=_count),
        patch("enigma.stats.embed_text", side_effect=_embed),
    ):
        return gather_stats()


# ── corpus ──────────────────────────────────────────────────────────────────


def test_corpus_counts_and_breakdowns() -> None:
    calls = [_call(status="done"), _call(status="done"), _call(status="failed")]
    notes = [_note(status="draft"), _note(status="validated"), _note(status="draft")]
    stats = _gather(calls, notes)
    assert stats.corpus.total_calls == 3
    assert stats.corpus.calls_by_status == {"done": 2, "failed": 1}
    assert stats.corpus.total_notes == 3
    assert stats.corpus.notes_by_status == {"draft": 2, "validated": 1}
    assert stats.corpus.qdrant_vectors == 42


def test_corpus_orphans_and_audio_hours() -> None:
    calls = [_call(duration=1800.0), _call(duration=1800.0)]  # 1 hora total
    notes = [_note(tags=["orphan"]), _note(tags=["x"]), _note(tags=["orphan"])]
    stats = _gather(calls, notes)
    assert stats.corpus.orphan_notes == 2
    assert stats.corpus.total_audio_hours == 1.0


def test_corpus_avg_notes_per_call() -> None:
    stats = _gather([_call(), _call()], [_note(), _note(), _note()])
    assert stats.corpus.avg_notes_per_call == 1.5


def test_empty_corpus_does_not_divide_by_zero() -> None:
    stats = _gather([], [])
    assert stats.corpus.total_calls == 0
    assert stats.corpus.avg_notes_per_call == 0.0
    assert stats.corpus.total_audio_hours == 0.0


# ── actividad ───────────────────────────────────────────────────────────────


def test_activity_time_windows() -> None:
    calls = [_call(days_ago=1), _call(days_ago=10), _call(days_ago=40)]
    stats = _gather(calls, [])
    assert stats.activity.calls_last_7d == 1
    assert stats.activity.calls_last_30d == 2


def test_notes_per_day_has_seven_days() -> None:
    stats = _gather([], [_note(days_ago=0), _note(days_ago=0), _note(days_ago=2)])
    assert len(stats.activity.notes_per_day) == 7
    today = datetime.now(tz=UTC).date().isoformat()
    assert stats.activity.notes_per_day[today] == 2


def test_notes_outside_window_excluded_from_per_day() -> None:
    stats = _gather([], [_note(days_ago=30)])
    assert sum(stats.activity.notes_per_day.values()) == 0


# ── salud ───────────────────────────────────────────────────────────────────


def test_health_probe_all_ok() -> None:
    stats = _gather([], [])
    assert stats.health.qdrant_ok is True
    assert stats.health.ollama_ok is True
    assert stats.health.embed_latency_ms is not None
    assert stats.health.embed_latency_ms >= 0.0


def test_health_probe_degrades_when_qdrant_down() -> None:
    stats = _gather([], [], qdrant_ok=False)
    assert stats.health.qdrant_ok is False
    assert stats.corpus.qdrant_vectors is None


def test_health_probe_degrades_when_ollama_down() -> None:
    stats = _gather([], [], embed_ok=False)
    assert stats.health.ollama_ok is False
    assert stats.health.embed_latency_ms is None
