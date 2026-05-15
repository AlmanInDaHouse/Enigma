"""Integration test: round-trip de backup con reindex real (T-505).

Marcado `@pytest.mark.integration`. Requiere Qdrant y Ollama corriendo. Hace
un ciclo completo backup → restore → reindex y verifica que Qdrant queda
poblado desde el Vault restaurado.

    uv run pytest -m integration tests/integration/test_backup_real.py
"""

import hashlib
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest

from enigma.backup import create_backup, restore_backup
from enigma.config import settings
from enigma.models.note import Note, NoteSource
from enigma.vault.writer import write_notes_to_inbox
from enigma.vector.qdrant_client import count, get_client


def _note(title: str) -> Note:
    body = f"Cuerpo de la nota {title}."
    return Note(
        id=uuid4(),
        title=title,
        body=body,
        tags=["t"],
        source=NoteSource(call_id=uuid4(), timestamp_start=0.0, timestamp_end=1.0),
        content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        extracted_by="qwen2.5:7b",
        created_at=datetime.now(tz=UTC),
    )


@pytest.fixture
def ephemeral_collection(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Colección Qdrant efímera; se borra al final."""
    collection = f"enigma_test_{uuid4().hex[:8]}"
    monkeypatch.setattr(settings, "qdrant_collection", collection)
    try:
        yield collection
    finally:
        client = get_client()
        if client.collection_exists(collection):
            client.delete_collection(collection)


@pytest.mark.integration
def test_backup_restore_rebuilds_qdrant(tmp_path: Path, ephemeral_collection: str) -> None:
    # Vault de origen con tres notas.
    src_vault = tmp_path / "src" / "vault"
    src_data = tmp_path / "src" / "data"
    src_data.mkdir(parents=True)
    write_notes_to_inbox([_note("Alpha"), _note("Beta"), _note("Gamma")], vault_path=src_vault)

    # Backup.
    manifest = create_backup(
        output_dir=tmp_path / "backups", vault_path=src_vault, data_path=src_data
    )
    assert manifest.vault_files == 3

    # Restore a un destino limpio + reindex real de Qdrant.
    dest_vault = tmp_path / "restored" / "vault"
    dest_data = tmp_path / "restored" / "data"
    report = restore_backup(
        manifest.archive_path,
        vault_path=dest_vault,
        data_path=dest_data,
        reindex=True,
    )

    assert report.vault_files == 3
    assert report.reindexed_notes == 3
    # Qdrant quedó poblado desde el Vault restaurado.
    assert count() == 3
