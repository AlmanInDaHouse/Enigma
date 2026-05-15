"""Tests unitarios para `enigma.backup` (T-505).

Round-trip backup → restore con `tmp_path`, sin tocar Qdrant (`reindex=False`).
"""

import zipfile
from pathlib import Path

import pytest

from enigma.backup import BackupError, create_backup, restore_backup


def _sample_tree(root: Path) -> tuple[Path, Path]:
    """Crea un Vault y un data/ de muestra bajo `root`. Devuelve (vault, data)."""
    vault = root / "vault"
    data = root / "data"
    (vault / "inbox").mkdir(parents=True)
    (vault / "notes").mkdir(parents=True)
    (vault / "inbox" / "nota-a.md").write_text("# Nota A\n\nCuerpo A.", encoding="utf-8")
    (vault / "notes" / "nota-b.md").write_text("# Nota B\n\nCuerpo B.", encoding="utf-8")
    (vault / "decisions.md").write_text("# Decisiones", encoding="utf-8")
    (data / "transcripts").mkdir(parents=True)
    (data / "transcripts" / "t1.json").write_text('{"call_id": "x"}', encoding="utf-8")
    (data / "enigma.db").write_bytes(b"\x00sqlite-fake")
    return vault, data


def _snapshot(directory: Path) -> dict[str, bytes]:
    """Mapa {ruta relativa: contenido} de todos los ficheros de `directory`."""
    return {
        p.relative_to(directory).as_posix(): p.read_bytes()
        for p in sorted(directory.rglob("*"))
        if p.is_file()
    }


# ── create_backup ───────────────────────────────────────────────────────────


def test_backup_manifest_counts(tmp_path: Path) -> None:
    vault, data = _sample_tree(tmp_path / "src")
    manifest = create_backup(output_dir=tmp_path / "backups", vault_path=vault, data_path=data)
    assert manifest.vault_files == 3
    assert manifest.data_files == 2
    assert manifest.archive_path.exists()
    assert manifest.size_bytes > 0


def test_archive_only_contains_vault_and_data(tmp_path: Path) -> None:
    """El archivo solo lleva entradas `vault/` y `data/` (nada de `.env` ni demás)."""
    vault, data = _sample_tree(tmp_path / "src")
    # Un `.env` colgando al lado NO debe acabar en el backup.
    (tmp_path / "src" / ".env").write_text("PYANNOTE_AUTH_TOKEN=secreto", encoding="utf-8")
    manifest = create_backup(output_dir=tmp_path / "backups", vault_path=vault, data_path=data)
    with zipfile.ZipFile(manifest.archive_path) as zf:
        names = zf.namelist()
    assert names, "el archivo no debería estar vacío"
    assert all(n.startswith(("vault/", "data/")) for n in names)
    assert not any(".env" in n for n in names)


# ── round-trip ──────────────────────────────────────────────────────────────


def test_backup_restore_roundtrip_is_identical(tmp_path: Path) -> None:
    vault, data = _sample_tree(tmp_path / "src")
    before_vault = _snapshot(vault)
    before_data = _snapshot(data)

    manifest = create_backup(output_dir=tmp_path / "backups", vault_path=vault, data_path=data)

    dest_vault = tmp_path / "restored" / "vault"
    dest_data = tmp_path / "restored" / "data"
    report = restore_backup(
        manifest.archive_path,
        vault_path=dest_vault,
        data_path=dest_data,
        reindex=False,
    )

    assert report.reindexed_notes is None
    assert report.vault_files == 3
    assert report.data_files == 2
    assert _snapshot(dest_vault) == before_vault
    assert _snapshot(dest_data) == before_data


# ── seguridad del restore ───────────────────────────────────────────────────


def test_restore_refuses_nonempty_target_without_force(tmp_path: Path) -> None:
    vault, data = _sample_tree(tmp_path / "src")
    manifest = create_backup(output_dir=tmp_path / "backups", vault_path=vault, data_path=data)
    dest_vault = tmp_path / "restored" / "vault"
    dest_data = tmp_path / "restored" / "data"
    dest_vault.mkdir(parents=True)
    (dest_vault / "ya-existe.md").write_text("no me pises", encoding="utf-8")

    with pytest.raises(BackupError, match="destino ya tiene datos"):
        restore_backup(
            manifest.archive_path,
            vault_path=dest_vault,
            data_path=dest_data,
            reindex=False,
        )


def test_restore_force_overwrites_nonempty_target(tmp_path: Path) -> None:
    vault, data = _sample_tree(tmp_path / "src")
    manifest = create_backup(output_dir=tmp_path / "backups", vault_path=vault, data_path=data)
    dest_vault = tmp_path / "restored" / "vault"
    dest_data = tmp_path / "restored" / "data"
    dest_vault.mkdir(parents=True)
    (dest_vault / "viejo.md").write_text("contenido viejo", encoding="utf-8")

    report = restore_backup(
        manifest.archive_path,
        vault_path=dest_vault,
        data_path=dest_data,
        reindex=False,
        force=True,
    )
    assert report.vault_files == 3
    assert (dest_vault / "inbox" / "nota-a.md").exists()


def test_restore_missing_archive_raises(tmp_path: Path) -> None:
    with pytest.raises(BackupError, match="No existe"):
        restore_backup(tmp_path / "no-existe.zip", reindex=False)


def test_restore_rejects_zip_slip(tmp_path: Path) -> None:
    """Una entrada que intenta escapar del destino se rechaza (zip-slip)."""
    evil = tmp_path / "evil.zip"
    with zipfile.ZipFile(evil, "w") as zf:
        zf.writestr("vault/../../escapado.md", "contenido malicioso")

    with pytest.raises(BackupError, match="fuera de destino"):
        restore_backup(
            evil,
            vault_path=tmp_path / "restored" / "vault",
            data_path=tmp_path / "restored" / "data",
            reindex=False,
        )
