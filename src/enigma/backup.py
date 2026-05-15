"""Snapshot y restauración del Vault + datos (T-505).

`create_backup()` empaqueta en un `.zip` lo que **no es reconstruible**:

- el **Vault** (`vault/`) — la fuente de verdad de las notas;
- `data/` — los audios y transcripts (entradas crudas) y `enigma.db`.

Qdrant **no se respalda**: es un artefacto derivado (CONSTITUTION §3). El
restore lo reconstruye reindexando el Vault con `reindex_vault()`. Así el
backup no depende del formato binario de Qdrant ni de su versión, y restaurar
valida de paso que el Vault produce un índice coherente.

`.env` se excluye a propósito: contiene secretos (`PYANNOTE_AUTH_TOKEN`) y se
recrea con `bootstrap.ps1`.

El backup está pensado para ejecutarse periódicamente (p.ej. semanal) vía
`enigma backup`; la cadencia es operativa.
"""

import zipfile
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from enigma.config import settings

_VAULT_PREFIX = "vault"
_DATA_PREFIX = "data"


class BackupError(RuntimeError):
    """Fallo al crear o restaurar un backup."""


class BackupManifest(BaseModel):
    """Resultado de `create_backup`."""

    model_config = ConfigDict(extra="forbid")

    created_at: datetime
    archive_path: Path
    vault_files: int
    data_files: int
    size_bytes: int


class RestoreReport(BaseModel):
    """Resultado de `restore_backup`."""

    model_config = ConfigDict(extra="forbid")

    archive_path: Path
    vault_files: int
    data_files: int
    reindexed_notes: int | None


def _add_tree(zf: zipfile.ZipFile, root: Path, prefix: str) -> int:
    """Añade recursivamente `root` al zip bajo `prefix/`. Devuelve nº de ficheros."""
    if not root.is_dir():
        return 0
    count = 0
    for path in sorted(root.rglob("*")):
        if path.is_file():
            arcname = f"{prefix}/{path.relative_to(root).as_posix()}"
            zf.write(path, arcname)
            count += 1
    return count


def create_backup(
    *,
    output_dir: Path | None = None,
    vault_path: Path | None = None,
    data_path: Path | None = None,
) -> BackupManifest:
    """Crea un snapshot `.zip` del Vault y de `data/`.

    Args:
        output_dir: Carpeta donde escribir el archivo. Default `settings.backup_dir`.
        vault_path: Raíz del Vault. Default `settings.enigma_vault_path`.
        data_path: Raíz de datos. Default `settings.enigma_data_path`.

    Returns:
        `BackupManifest` con la ruta del archivo y los conteos.
    """
    vault = vault_path if vault_path is not None else settings.enigma_vault_path
    data = data_path if data_path is not None else settings.enigma_data_path
    out = output_dir if output_dir is not None else settings.backup_dir
    out.mkdir(parents=True, exist_ok=True)

    created_at = datetime.now(tz=UTC)
    archive_path = out / f"enigma-backup-{created_at:%Y%m%d-%H%M%S}.zip"

    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zf:
        vault_files = _add_tree(zf, vault, _VAULT_PREFIX)
        data_files = _add_tree(zf, data, _DATA_PREFIX)

    return BackupManifest(
        created_at=created_at,
        archive_path=archive_path,
        vault_files=vault_files,
        data_files=data_files,
        size_bytes=archive_path.stat().st_size,
    )


def _has_content(directory: Path) -> bool:
    """`True` si `directory` existe y contiene algo."""
    return directory.is_dir() and any(directory.iterdir())


def _safe_target(base: Path, relative: str) -> Path:
    """Resuelve `base/relative` rechazando rutas que escapen de `base` (zip-slip)."""
    target = (base / relative).resolve()
    if base.resolve() not in target.parents and target != base.resolve():
        raise BackupError(f"Entrada de backup fuera de destino: {relative}")
    return target


def restore_backup(
    archive_path: Path,
    *,
    vault_path: Path | None = None,
    data_path: Path | None = None,
    reindex: bool = True,
    force: bool = False,
) -> RestoreReport:
    """Restaura un snapshot creado por `create_backup`.

    Es **destructivo**: extrae sobre el Vault y `data/` de destino. Si alguno
    ya tiene contenido y `force` es `False`, se aborta sin tocar nada.

    Args:
        archive_path: Ruta del `.zip` a restaurar.
        vault_path: Destino del Vault. Default `settings.enigma_vault_path`.
        data_path: Destino de datos. Default `settings.enigma_data_path`.
        reindex: Si `True`, reconstruye Qdrant con `reindex_vault()`.
        force: Permite restaurar aunque el destino tenga contenido.

    Returns:
        `RestoreReport` con los conteos y, si aplica, las notas reindexadas.

    Raises:
        BackupError: si el archivo no existe, el destino no está vacío sin
            `force`, o una entrada del zip intenta escapar del destino.
    """
    if not archive_path.is_file():
        raise BackupError(f"No existe el archivo de backup: {archive_path}")

    vault = vault_path if vault_path is not None else settings.enigma_vault_path
    data = data_path if data_path is not None else settings.enigma_data_path

    if not force and (_has_content(vault) or _has_content(data)):
        raise BackupError(
            "El destino ya tiene datos. Usa --force para sobrescribir "
            "(restaura antes el estado actual si lo necesitas).",
        )

    vault_files = 0
    data_files = 0
    with zipfile.ZipFile(archive_path, "r") as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = info.filename
            if name.startswith(f"{_VAULT_PREFIX}/"):
                target = _safe_target(vault, name[len(_VAULT_PREFIX) + 1 :])
                vault_files += 1
            elif name.startswith(f"{_DATA_PREFIX}/"):
                target = _safe_target(data, name[len(_DATA_PREFIX) + 1 :])
                data_files += 1
            else:
                continue  # entrada ajena al esquema del backup
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(zf.read(info))

    reindexed_notes: int | None = None
    if reindex:
        from enigma.vector.reindexer import reindex_vault

        report = reindex_vault(vault_path=vault)
        reindexed_notes = report.notes_indexed

    return RestoreReport(
        archive_path=archive_path,
        vault_files=vault_files,
        data_files=data_files,
        reindexed_notes=reindexed_notes,
    )
