"""File watcher del Vault: re-vectoriza notas al detectar cambios (T-204).

Usa `watchdog` para observar `vault/`. Cuando un `.md` se crea o modifica, la
nota se re-vectoriza y se *upsertea* en Qdrant; cuando se borra, su vector se
elimina (RF-11).

Para poder borrar el vector de un fichero eliminado — que ya no se puede
leer — el handler mantiene un cache `path → note_id` que actualiza en cada
create/modify procesado con éxito.
"""

import logging
import time
from pathlib import Path
from uuid import UUID

from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from enigma.config import settings
from enigma.vault.reader import read_note
from enigma.vector.embedder import embed_note
from enigma.vector.qdrant_client import (
    delete_vector,
    ensure_collection,
    note_payload,
    upsert_vector,
)

_log = logging.getLogger(__name__)


def vectorize_note_file(path: Path) -> UUID | None:
    """Lee, embebe y *upsertea* la nota en `path`.

    Returns:
        El `note_id` vectorizado, o `None` si el fichero no es una nota
        Enigma válida.
    """
    note = read_note(path)
    if note is None:
        return None
    vector = embed_note(note)
    upsert_vector(note.id, vector, note_payload(note))
    return note.id


class VaultEventHandler(FileSystemEventHandler):  # type: ignore[misc]  # watchdog sin stubs
    """Handler watchdog: vectoriza `.md` creados/modificados, borra los eliminados."""

    def __init__(self) -> None:
        super().__init__()
        # path (str) → note_id, para borrar el vector cuando el fichero se elimine.
        self._path_to_id: dict[str, UUID] = {}

    @staticmethod
    def _is_markdown(event: FileSystemEvent) -> bool:
        return not event.is_directory and str(event.src_path).endswith(".md")

    @staticmethod
    def _cache_key(src_path: str | bytes) -> str:
        """Clave de cache normalizada — `Path` unifica separadores entre OS."""
        return str(Path(str(src_path)))

    def on_created(self, event: FileSystemEvent) -> None:
        if self._is_markdown(event):
            self._vectorize(Path(str(event.src_path)))

    def on_modified(self, event: FileSystemEvent) -> None:
        if self._is_markdown(event):
            self._vectorize(Path(str(event.src_path)))

    def on_deleted(self, event: FileSystemEvent) -> None:
        if not self._is_markdown(event):
            return
        note_id = self._path_to_id.pop(self._cache_key(event.src_path), None)
        if note_id is not None:
            delete_vector(note_id)

    def _vectorize(self, path: Path) -> None:
        """Re-vectoriza `path`; un fallo se registra pero no detiene el watcher."""
        try:
            note_id = vectorize_note_file(path)
        except Exception:
            _log.warning("Fallo al vectorizar %s", path)
            return
        if note_id is not None:
            self._path_to_id[self._cache_key(str(path))] = note_id


def run_watcher(vault_path: Path | None = None) -> None:
    """Arranca el file watcher del Vault. Bloqueante hasta `Ctrl-C`.

    Args:
        vault_path: Raíz del Vault a observar. Default `settings.enigma_vault_path`.
    """
    root = vault_path if vault_path is not None else settings.enigma_vault_path
    root.mkdir(parents=True, exist_ok=True)
    ensure_collection()

    observer = Observer()
    observer.schedule(VaultEventHandler(), str(root), recursive=True)
    observer.start()
    _log.info("Watcher activo sobre %s", root)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
