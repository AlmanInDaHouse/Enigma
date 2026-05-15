"""Tests para el comando `enigma contradictions` (T-404)."""

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from enigma.agent.contradictions import ContradictionIndexResult
from enigma.cli import app

runner = CliRunner()


def _result() -> ContradictionIndexResult:
    return ContradictionIndexResult(
        contradictions=[],
        notes_scanned=12,
        pairs_evaluated=7,
        index_path=Path("/vault/contradictions.md"),
    )


def test_contradictions_reports_metrics() -> None:
    with patch("enigma.agent.contradictions.build_contradiction_index", return_value=_result()):
        result = runner.invoke(app, ["contradictions"])
    assert result.exit_code == 0
    assert "12" in result.output
    assert "regenerado" in result.output
