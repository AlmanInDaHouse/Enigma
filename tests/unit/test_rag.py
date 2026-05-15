"""Tests unitarios para `enigma.agent.rag` (T-302).

Mockean `search_notes`, `load_notes_by_ids` y el cliente Ollama para verificar
el flujo RAG y el parseo de citas sin tocar Qdrant, el Vault ni el LLM real.
"""

import hashlib
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from enigma.agent.rag import NO_CONTEXT_ANSWER, Citation, RagError, answer_question
from enigma.models.note import Note, NoteSource
from enigma.search import SearchResult
from enigma.vault.writer import note_stem


def _note(title: str = "Estrategia padel", body: str = "Los clubs tienen socios.") -> Note:
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


def _source(note_id: UUID, title: str = "Estrategia padel") -> SearchResult:
    return SearchResult(
        note_id=note_id,
        title=title,
        score=0.9,
        tags=["t"],
        status="draft",
        call_id=uuid4(),
        created_at=datetime.now(tz=UTC),
    )


def _llm_client(answer: str) -> MagicMock:
    """Cliente Ollama falso cuyo `.chat` responde con `answer` en texto libre."""
    client = MagicMock()
    client.chat.return_value = {"message": {"content": answer}}
    return client


# ── flujo nominal ───────────────────────────────────────────────────────────


def test_answer_question_returns_answer_and_sources() -> None:
    note = _note()
    stem = note_stem(note.id, note.title)
    answer_text = f"Captamos socios por densidad de clubs [[{stem}|{note.title}]]."
    with (
        patch("enigma.agent.rag.search_notes", return_value=[_source(note.id)]),
        patch("enigma.agent.rag.load_notes_by_ids", return_value={note.id: note}),
        patch("enigma.agent.rag._client", return_value=_llm_client(answer_text)),
    ):
        result = answer_question("¿Cómo captamos socios?")
    assert result.question == "¿Cómo captamos socios?"
    assert result.answer == answer_text
    assert len(result.sources) == 1
    assert len(result.citations) == 1
    assert result.citations[0].note_id == note.id


def test_citation_carries_note_metadata() -> None:
    note = _note(title="Pricing por volumen")
    stem = note_stem(note.id, note.title)
    with (
        patch("enigma.agent.rag.search_notes", return_value=[_source(note.id)]),
        patch("enigma.agent.rag.load_notes_by_ids", return_value={note.id: note}),
        patch(
            "enigma.agent.rag._client",
            return_value=_llm_client(f"Respuesta [[{stem}|Pricing por volumen]]."),
        ),
    ):
        result = answer_question("pregunta")
    citation = result.citations[0]
    assert isinstance(citation, Citation)
    assert citation.note_id == note.id
    assert citation.title == "Pricing por volumen"
    assert citation.stem == stem


def test_top_k_and_model_are_propagated() -> None:
    note = _note()
    with (
        patch("enigma.agent.rag.search_notes", return_value=[_source(note.id)]) as mock_search,
        patch("enigma.agent.rag.load_notes_by_ids", return_value={note.id: note}),
        patch("enigma.agent.rag._client", return_value=_llm_client("ok")) as mock_client,
    ):
        answer_question("pregunta", top_k=8, model="llama3.1:8b")
    assert mock_search.call_args.kwargs["top_k"] == 8
    assert mock_client.return_value.chat.call_args.kwargs["model"] == "llama3.1:8b"


# ── parseo de citas ─────────────────────────────────────────────────────────


def test_hallucinated_wikilink_is_not_counted_as_citation() -> None:
    """Un `[[wikilink]]` que no casa con ninguna nota recuperada se ignora."""
    note = _note()
    answer_text = "Respuesta con cita inventada [[nota-fantasma-00000000|Fantasma]]."
    with (
        patch("enigma.agent.rag.search_notes", return_value=[_source(note.id)]),
        patch("enigma.agent.rag.load_notes_by_ids", return_value={note.id: note}),
        patch("enigma.agent.rag._client", return_value=_llm_client(answer_text)),
    ):
        result = answer_question("pregunta")
    assert result.citations == []


def test_repeated_citation_is_deduplicated() -> None:
    note = _note()
    stem = note_stem(note.id, note.title)
    answer_text = f"Primero [[{stem}|{note.title}]] y luego otra vez [[{stem}|{note.title}]]."
    with (
        patch("enigma.agent.rag.search_notes", return_value=[_source(note.id)]),
        patch("enigma.agent.rag.load_notes_by_ids", return_value={note.id: note}),
        patch("enigma.agent.rag._client", return_value=_llm_client(answer_text)),
    ):
        result = answer_question("pregunta")
    assert len(result.citations) == 1


# ── retrieval vacío ─────────────────────────────────────────────────────────


def test_no_sources_returns_deterministic_answer_without_llm() -> None:
    client = _llm_client("no debería llamarse")
    with (
        patch("enigma.agent.rag.search_notes", return_value=[]),
        patch("enigma.agent.rag.load_notes_by_ids", return_value={}),
        patch("enigma.agent.rag._client", return_value=client),
    ):
        result = answer_question("pregunta sin notas")
    assert result.answer == NO_CONTEXT_ANSWER
    assert result.citations == []
    client.chat.assert_not_called()


def test_sources_without_disk_notes_returns_deterministic_answer() -> None:
    """Puntos Qdrant huérfanos (sin fichero en disco) → respuesta determinista."""
    note_id = uuid4()
    client = _llm_client("no debería llamarse")
    with (
        patch("enigma.agent.rag.search_notes", return_value=[_source(note_id)]),
        patch("enigma.agent.rag.load_notes_by_ids", return_value={}),
        patch("enigma.agent.rag._client", return_value=client),
    ):
        result = answer_question("pregunta")
    assert result.answer == NO_CONTEXT_ANSWER
    assert len(result.sources) == 1  # el source se reporta aunque no haya fichero
    client.chat.assert_not_called()


# ── fallo del LLM ───────────────────────────────────────────────────────────


def test_llm_failure_raises_rag_error() -> None:
    note = _note()
    bad_client = MagicMock()
    bad_client.chat.side_effect = ollama_response_error()
    with (
        patch("enigma.agent.rag.search_notes", return_value=[_source(note.id)]),
        patch("enigma.agent.rag.load_notes_by_ids", return_value={note.id: note}),
        patch("enigma.agent.rag._client", return_value=bad_client),
        pytest.raises(RagError),
    ):
        answer_question("pregunta")


def ollama_response_error() -> Exception:
    """Construye un `ollama.ResponseError` para simular un fallo del LLM."""
    import ollama

    return ollama.ResponseError("boom")


# ── reranking (T-304) ───────────────────────────────────────────────────────


def test_rerank_off_by_default_skips_reranker(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con `rerank_enabled=False` no se llama al reranker y se recupera top_k."""
    monkeypatch.setattr("enigma.config.settings.rerank_enabled", False)
    note = _note()
    with (
        patch("enigma.agent.rag.search_notes", return_value=[_source(note.id)]) as mock_search,
        patch("enigma.agent.rag.load_notes_by_ids", return_value={note.id: note}),
        patch("enigma.agent.rag._client", return_value=_llm_client("ok")),
        patch("enigma.vector.reranker.rerank_notes") as mock_rerank,
    ):
        answer_question("pregunta", top_k=5)
    assert mock_search.call_args.kwargs["top_k"] == 5
    mock_rerank.assert_not_called()


def test_rerank_on_retrieves_pool_and_reranks(monkeypatch: pytest.MonkeyPatch) -> None:
    """Con rerank activo: recupera el pool ampliado y pasa por el reranker."""
    monkeypatch.setattr("enigma.config.settings.rerank_enabled", True)
    monkeypatch.setattr("enigma.config.settings.rerank_candidate_pool", 20)
    notes = [_note(title=f"N{i}") for i in range(3)]
    sources = [_source(n.id, title=n.title) for n in notes]
    notes_by_id = {n.id: n for n in notes}
    # El reranker invierte el orden: N2, N1, N0.
    reranked = list(reversed(notes))
    with (
        patch("enigma.agent.rag.search_notes", return_value=sources) as mock_search,
        patch("enigma.agent.rag.load_notes_by_ids", return_value=notes_by_id),
        patch("enigma.agent.rag._client", return_value=_llm_client("ok")),
        patch("enigma.vector.reranker.rerank_notes", return_value=reranked) as mock_rerank,
    ):
        result = answer_question("pregunta", top_k=2)
    assert mock_search.call_args.kwargs["top_k"] == 20
    mock_rerank.assert_called_once()
    # Solo las top_k=2 tras el rerank; en el nuevo orden (N2 primero).
    assert [s.title for s in result.sources] == ["N2", "N1"]


def test_rerank_param_overrides_setting(monkeypatch: pytest.MonkeyPatch) -> None:
    """El parámetro `rerank=True` activa el reranker aunque el setting esté off."""
    monkeypatch.setattr("enigma.config.settings.rerank_enabled", False)
    note = _note()
    with (
        patch("enigma.agent.rag.search_notes", return_value=[_source(note.id)]),
        patch("enigma.agent.rag.load_notes_by_ids", return_value={note.id: note}),
        patch("enigma.agent.rag._client", return_value=_llm_client("ok")),
        patch("enigma.vector.reranker.rerank_notes", return_value=[note]) as mock_rerank,
    ):
        answer_question("pregunta", rerank=True)
    mock_rerank.assert_called_once()
