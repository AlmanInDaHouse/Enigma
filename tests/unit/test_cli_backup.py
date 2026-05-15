"""Tests para los comandos `enigma backup` y `enigma restore` (T-505)."""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from enigma.backup import BackupError, BackupManifest, RestoreReport
from enigma.cli import app

runner = CliRunner()


def _manifest(tmp: Path) -> BackupManifest:
    archive = tmp / "enigma-backup-20260516-100000.zip"
    archive.write_bytes(b"fake-zip")
    return BackupManifest(
        created_at=datetime(2026, 5, 16, 10, 0, tzinfo=UTC),
        archive_path=archive,
        vault_files=37,
        data_files=8,
        size_bytes=2_500_000,
    )


def test_backup_reports_archive(tmp_path: Path) -> None:
    with patch("enigma.backup.create_backup", return_value=_manifest(tmp_path)):
        result = runner.invoke(app, ["backup"])
    assert result.exit_code == 0
    assert "Backup creado" in result.output
    assert "37" in result.output


def test_restore_reports_counts(tmp_path: Path) -> None:
    archive = tmp_path / "backup.zip"
    archive.write_bytes(b"fake-zip")
    report = RestoreReport(archive_path=archive, vault_files=37, data_files=8, reindexed_notes=37)
    with patch("enigma.backup.restore_backup", return_value=report):
        result = runner.invoke(app, ["restore", str(archive)])
    assert result.exit_code == 0
    assert "restaurado" in result.output
    assert "reindexadas" in result.output


def test_restore_handles_backup_error(tmp_path: Path) -> None:
    archive = tmp_path / "backup.zip"
    archive.write_bytes(b"fake-zip")
    with patch(
        "enigma.backup.restore_backup",
        side_effect=BackupError("el destino ya tiene datos"),
    ):
        result = runner.invoke(app, ["restore", str(archive)])
    assert result.exit_code == 1
    assert "Error" in result.output


def test_restore_rejects_missing_archive() -> None:
    result = runner.invoke(app, ["restore", "no-existe.zip"])
    assert result.exit_code != 0
