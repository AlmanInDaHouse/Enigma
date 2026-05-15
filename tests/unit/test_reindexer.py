"""Tests unitarios para `enigma.vector.reindexer` (T-203).

Mockea embedder + Qdrant + lectura del Vault para verificar la orquestación.
El test real (Qdrant + Ollama + Vault) vive en
`tests/integration/test_reindexer_real.py`.
"""

import hashlib
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

from enigma.models.note import Note, NoteSource
from enigma.vector.embedder import EMBEDDING_DIM
from enigma.vector.reindexer import ReindexReport, reindex_vault


def _note(body: str = "Cuerpo de la nota.") -> Note:
    return Note(
        id=uuid4(),
        title="Idea",
        body=body,
        tags=["t"],
        source=NoteSource(call_id=uuid4(), timestamp_start=0.0, timestamp_end=1.0),
        content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        extracted_by="qwen2.5:7b",
        created_at=datetime.now(tz=UTC),
    )


def _patch_reindexer(
    *,
    notes: list[Note | None],
    collection_points: int,
) -> tuple[ExitStack, dict[str, MagicMock]]:
    """Patchea las deps de `reindexer`. Devuelve (stack, mocks)."""
    summaries = [MagicMock(path=Path(f"/note_{i}.md")) for i in range(len(notes))]
    mocks = {
        "ensure": MagicMock(),
        "list": MagicMock(return_value=summaries),
        "read": MagicMock(side_effect=notes),
        "embed": MagicMock(return_value=[0.1] * EMBEDDING_DIM),
        "upsert": MagicMock(),
        "count": MagicMock(return_value=collection_points),
    }
    stack = ExitStack()
    stack.enter_context(patch("enigma.vector.reindexer.ensure_collection", mocks["ensure"]))
    stack.enter_context(patch("enigma.vector.reindexer.list_vault_notes", mocks["list"]))
    stack.enter_context(patch("enigma.vector.reindexer.read_note", mocks["read"]))
    stack.enter_context(patch("enigma.vector.reindexer.embed_note", mocks["embed"]))
    stack.enter_context(patch("enigma.vector.reindexer.upsert_vector", mocks["upsert"]))
    stack.enter_context(patch("enigma.vector.reindexer.count", mocks["count"]))
    return stack, mocks


def test_reindex_embeds_and_upserts_each_note() -> None:
    notes: list[Note | None] = [_note(), _note()]
    stack, mocks = _patch_reindexer(notes=notes, collection_points=2)
    with stack:
        report = reindex_vault()
    assert isinstance(report, ReindexReport)
    assert report.notes_indexed == 2
    assert mocks["embed"].call_count == 2
    assert mocks["upsert"].call_count == 2
    assert mocks["ensure"].call_count == 1


def test_reindex_report_metrics() -> None:
    notes: list[Note | None] = [_note(), _note(), _note()]
    stack, _ = _patch_reindexer(notes=notes, collection_points=3)
    with stack:
        report = reindex_vault()
    assert report.notes_indexed == 3
    assert report.vector_dim == EMBEDDING_DIM
    assert report.collection_points == 3
    assert report.elapsed_seconds >= 0.0
    assert report.notes_per_second >= 0.0


def test_reindex_skips_unreadable_notes() -> None:
    """Notas que `read_note` no puede parsear (None) se descartan."""
    notes: list[Note | None] = [_note(), None, _note()]
    stack, mocks = _patch_reindexer(notes=notes, collection_points=2)
    with stack:
        report = reindex_vault()
    assert report.notes_indexed == 2
    assert mocks["upsert"].call_count == 2


def test_reindex_empty_vault() -> None:
    stack, mocks = _patch_reindexer(notes=[], collection_points=0)
    with stack:
        report = reindex_vault()
    assert report.notes_indexed == 0
    assert report.notes_per_second == 0.0
    mocks["upsert"].assert_not_called()


def test_reindex_upserts_with_note_id_and_payload() -> None:
    note = _note()
    stack, mocks = _patch_reindexer(notes=[note], collection_points=1)
    with stack:
        reindex_vault()
    args = mocks["upsert"].call_args.args
    assert args[0] == note.id  # primer arg posicional: note_id
    payload = args[2]  # tercer arg: payload
    assert payload["title"] == note.title
    assert payload["content_hash"] == note.content_hash
    assert payload["call_id"] == str(note.source.call_id)
