"""Tests para el comando `enigma tasks` (T-403)."""

from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from enigma.agent.tasks_extractor import TaskIndexResult, TasksError
from enigma.cli import app

runner = CliRunner()


def _result() -> TaskIndexResult:
    return TaskIndexResult(
        tasks=[],
        calls_scanned=5,
        calls_with_tasks=2,
        index_path=Path("/vault/tasks.md"),
    )


def test_tasks_reports_metrics() -> None:
    with patch("enigma.agent.tasks_extractor.build_task_index", return_value=_result()):
        result = runner.invoke(app, ["tasks"])
    assert result.exit_code == 0
    assert "5" in result.output
    assert "regenerado" in result.output


def test_tasks_handles_error() -> None:
    with patch(
        "enigma.agent.tasks_extractor.build_task_index",
        side_effect=TasksError("LLM caído"),
    ):
        result = runner.invoke(app, ["tasks"])
    assert result.exit_code == 1
    assert "Error" in result.output
