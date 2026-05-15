"""Tests para el comando `enigma themes` (T-405)."""

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from enigma.agent.themes import ThemeIndexResult
from enigma.cli import app

runner = CliRunner()


def _result() -> ThemeIndexResult:
    return ThemeIndexResult(
        themes=[],
        notes_scanned=20,
        clusters_found=6,
        index_path=Path("/vault/recurring-themes.md"),
    )


def test_themes_reports_metrics() -> None:
    with patch("enigma.agent.themes.build_recurring_themes_index", return_value=_result()):
        result = runner.invoke(app, ["themes"])
    assert result.exit_code == 0
    assert "20" in result.output
    assert "regenerado" in result.output
