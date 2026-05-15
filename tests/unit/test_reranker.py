"""Tests unitarios para `enigma.vector.reranker` (T-304).

Mockean el cross-encoder (`_encoder`) para verificar el reordenado sin
descargar ni cargar el modelo real.
"""

import hashlib
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import uuid4

from enigma.models.note import Note, NoteSource
from enigma.vector.reranker import rerank_notes


def _note(title: str, body: str) -> Note:
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


def _encoder_with_scores(scores: list[float]) -> MagicMock:
    """Cross-encoder falso cuyo `.predict` devuelve `scores` en orden de entrada."""
    encoder = MagicMock()
    encoder.predict.return_value = scores
    return encoder


def test_rerank_reorders_by_descending_score() -> None:
    notes = [_note("A", "cuerpo a"), _note("B", "cuerpo b"), _note("C", "cuerpo c")]
    # El encoder considera C el más relevante, luego A, luego B.
    with patch(
        "enigma.vector.reranker._encoder",
        return_value=_encoder_with_scores([0.5, 0.1, 0.9]),
    ):
        ranked = rerank_notes("consulta", notes)
    assert [n.title for n in ranked] == ["C", "A", "B"]


def test_rerank_empty_list_returns_empty() -> None:
    with patch("enigma.vector.reranker._encoder") as mock_encoder:
        assert rerank_notes("consulta", []) == []
    mock_encoder.assert_not_called()


def test_rerank_scores_query_against_each_body() -> None:
    notes = [_note("A", "cuerpo a"), _note("B", "cuerpo b")]
    encoder = _encoder_with_scores([0.3, 0.7])
    with patch("enigma.vector.reranker._encoder", return_value=encoder):
        rerank_notes("mi consulta", notes)
    pairs = encoder.predict.call_args.args[0]
    assert pairs == [("mi consulta", "cuerpo a"), ("mi consulta", "cuerpo b")]


def test_rerank_single_note_returned_as_is() -> None:
    note = _note("Solo", "cuerpo único")
    with patch(
        "enigma.vector.reranker._encoder",
        return_value=_encoder_with_scores([0.42]),
    ):
        ranked = rerank_notes("consulta", [note])
    assert ranked == [note]


def test_rerank_uses_model_override() -> None:
    notes = [_note("A", "cuerpo a")]
    with patch("enigma.vector.reranker._encoder", return_value=_encoder_with_scores([0.1])) as m:
        rerank_notes("consulta", notes, model="cross-encoder/otro-modelo")
    m.assert_called_once_with("cross-encoder/otro-modelo")
