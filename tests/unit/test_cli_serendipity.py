"""Tests para el comando `enigma serendipity` (T-406)."""

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from enigma.agent.serendipity import SerendipityResult
from enigma.cli import app

runner = CliRunner()


def _result() -> SerendipityResult:
    return SerendipityResult(
        suggestions=[],
        notes_scanned=30,
        pairs_evaluated=14,
        index_path=Path("/vault/serendipity.md"),
    )


def test_serendipity_reports_metrics() -> None:
    with patch("enigma.agent.serendipity.build_serendipity_index", return_value=_result()):
        result = runner.invoke(app, ["serendipity"])
    assert result.exit_code == 0
    assert "30" in result.output
    assert "regenerado" in result.output
