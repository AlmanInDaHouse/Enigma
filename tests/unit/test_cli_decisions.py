"""Tests para el comando `enigma decisions` (T-402)."""

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from enigma.agent.decisions import DecisionIndexResult, DecisionsError
from enigma.cli import app

runner = CliRunner()


def _result() -> DecisionIndexResult:
    return DecisionIndexResult(
        decisions=[],
        calls_scanned=4,
        calls_with_decisions=3,
        index_path=Path("/vault/decisions.md"),
    )


def test_decisions_reports_metrics() -> None:
    with patch("enigma.agent.decisions.build_decision_index", return_value=_result()):
        result = runner.invoke(app, ["decisions"])
    assert result.exit_code == 0
    assert "4" in result.output
    assert "regenerado" in result.output


def test_decisions_handles_error() -> None:
    with patch(
        "enigma.agent.decisions.build_decision_index",
        side_effect=DecisionsError("LLM caído"),
    ):
        result = runner.invoke(app, ["decisions"])
    assert result.exit_code == 1
    assert "Error" in result.output
