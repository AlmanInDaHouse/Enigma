"""Integration test: file watcher real del Vault (T-204).

Marcado `@pytest.mark.integration`. Requiere Qdrant y Ollama. Arranca un
`Observer` real, escribe una nota en el Vault y verifica que el vector
aparece en Qdrant en < 5 s (criterio de aceptación T-204).

    uv run pytest -m integration tests/integration/test_watcher_real.py
"""

import hashlib
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from watchdog.observers import Observer

from enigma.config import settings
from enigma.models.note import Note, NoteSource
from enigma.vault.writer import upsert_note
from enigma.vector.qdrant_client import count, ensure_collection, get_client
from enigma.workers.watcher import VaultEventHandler


def _note(title: str = "Idea watcher") -> Note:
    body = "Cuerpo de la nota observada por el watcher."
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
def isolated_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Vault temporal + colección Qdrant efímera."""
    collection = f"enigma_test_{uuid4().hex[:8]}"
    monkeypatch.setattr(settings, "enigma_vault_path", tmp_path)
    monkeypatch.setattr(settings, "qdrant_collection", collection)
    (tmp_path / "inbox").mkdir(parents=True, exist_ok=True)
    ensure_collection()
    try:
        yield collection
    finally:
        client = get_client()
        if client.collection_exists(collection):
            client.delete_collection(collection)


@pytest.mark.integration
def test_watcher_vectorizes_new_note_within_5s(isolated_env: str) -> None:
    """Escribir una nota en el Vault la vectoriza en Qdrant en < 5 s."""
    observer = Observer()
    observer.schedule(
        VaultEventHandler(),
        str(settings.enigma_vault_path),
        recursive=True,
    )
    observer.start()
    try:
        upsert_note(_note(), vault_dir=settings.enigma_vault_path / "inbox")

        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            if count() >= 1:
                break
            time.sleep(0.2)

        assert count() == 1, "la nota no se vectorizó dentro de los 5 s"
    finally:
        observer.stop()
        observer.join()
