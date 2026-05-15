"""Tests para el comando `enigma stats` (T-504)."""

from unittest.mock import patch

from typer.testing import CliRunner

from enigma.cli import app
from enigma.stats import ActivityStats, CorpusStats, EnigmaStats, HealthProbe

runner = CliRunner()


def _stats(*, empty: bool = False) -> EnigmaStats:
    return EnigmaStats(
        corpus=CorpusStats(
            total_calls=0 if empty else 4,
            calls_by_status={} if empty else {"done": 4},
            total_notes=0 if empty else 37,
            notes_by_status={} if empty else {"draft": 30, "validated": 7},
            orphan_notes=0 if empty else 5,
            qdrant_vectors=None if empty else 37,
            total_audio_hours=0.0 if empty else 2.5,
            avg_notes_per_call=0.0 if empty else 9.2,
        ),
        activity=ActivityStats(
            calls_last_7d=0 if empty else 2,
            calls_last_30d=0 if empty else 4,
            notes_per_day={"2026-05-15": 0 if empty else 12, "2026-05-16": 0 if empty else 4},
        ),
        health=HealthProbe(
            qdrant_ok=not empty,
            ollama_ok=not empty,
            embed_latency_ms=None if empty else 48.0,
        ),
    )


def test_stats_renders_dashboard() -> None:
    with patch("enigma.stats.gather_stats", return_value=_stats()):
        result = runner.invoke(app, ["stats"])
    assert result.exit_code == 0
    assert "Corpus" in result.output
    assert "Actividad" in result.output
    assert "Salud" in result.output
    assert "37" in result.output  # total de notas


def test_stats_empty_corpus_does_not_crash() -> None:
    with patch("enigma.stats.gather_stats", return_value=_stats(empty=True)):
        result = runner.invoke(app, ["stats"])
    assert result.exit_code == 0
    assert "Corpus" in result.output


def test_stats_shows_unavailable_health() -> None:
    with patch("enigma.stats.gather_stats", return_value=_stats(empty=True)):
        result = runner.invoke(app, ["stats"])
    assert result.exit_code == 0
    assert "no disponible" in result.output
