"""Tests unitarios para `enigma.vault.linker` (T-205).

Mockea `embed_note`, `search` y el cliente Ollama para verificar el filtrado
de candidatos y la validación LLM sin tocar Qdrant ni el modelo real.
"""

import hashlib
import json
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

from enigma.config import settings
from enigma.models.note import Note, NoteSource
from enigma.vault.linker import WikilinkSuggestion, suggest_wikilinks
from enigma.vector.qdrant_client import SearchHit


def _note(note_id: UUID | None = None) -> Note:
    body = "Los clubs de padel tienen alta densidad de socios."
    return Note(
        id=note_id if note_id is not None else uuid4(),
        title="Estrategia padel",
        body=body,
        tags=["t"],
        source=NoteSource(call_id=uuid4(), timestamp_start=0.0, timestamp_end=1.0),
        content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        extracted_by="qwen2.5:7b",
        created_at=datetime.now(tz=UTC),
    )


def _hit(score: float, *, note_id: UUID | None = None, title: str = "Vecina") -> SearchHit:
    return SearchHit(
        note_id=note_id if note_id is not None else uuid4(),
        score=score,
        payload={"title": title},
    )


def _llm_client(verdict: bool) -> MagicMock:
    """Cliente Ollama falso cuyo `.chat` responde {"link": verdict}."""
    client = MagicMock()
    client.chat.return_value = {"message": {"content": json.dumps({"link": verdict})}}
    return client


@pytest.fixture(autouse=True)
def _llm_validation_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """Por defecto los tests corren con validación LLM activada."""
    monkeypatch.setattr(settings, "link_llm_validation", True)
    monkeypatch.setattr(settings, "link_similarity_threshold", 0.78)
    monkeypatch.setattr(settings, "link_top_k_candidates", 5)


# ── filtrado de candidatos ──────────────────────────────────────────────────


def test_suggest_filters_below_threshold() -> None:
    note = _note()
    hits = [_hit(0.90), _hit(0.60), _hit(0.85)]  # 0.60 < 0.78 → descartado
    with (
        patch("enigma.vault.linker.embed_note", return_value=[0.1] * 768),
        patch("enigma.vault.linker.search", return_value=hits),
        patch("enigma.vault.linker._client", return_value=_llm_client(True)),
    ):
        suggestions = suggest_wikilinks(note)
    assert len(suggestions) == 2
    assert all(s.score >= 0.78 for s in suggestions)


def test_suggest_excludes_the_note_itself() -> None:
    note = _note()
    hits = [_hit(0.95, note_id=note.id), _hit(0.88)]  # el primero es la propia nota
    with (
        patch("enigma.vault.linker.embed_note", return_value=[0.1] * 768),
        patch("enigma.vault.linker.search", return_value=hits),
        patch("enigma.vault.linker._client", return_value=_llm_client(True)),
    ):
        suggestions = suggest_wikilinks(note)
    assert len(suggestions) == 1
    assert suggestions[0].target_note_id != note.id


def test_suggest_respects_top_k() -> None:
    note = _note()
    hits = [_hit(0.80 + i * 0.01) for i in range(10)]
    with (
        patch("enigma.vault.linker.embed_note", return_value=[0.1] * 768),
        patch("enigma.vault.linker.search", return_value=hits),
        patch("enigma.vault.linker._client", return_value=_llm_client(True)),
    ):
        suggestions = suggest_wikilinks(note)
    assert len(suggestions) <= settings.link_top_k_candidates


# ── validación LLM ──────────────────────────────────────────────────────────


def test_suggest_drops_candidates_rejected_by_llm() -> None:
    note = _note()
    hits = [_hit(0.90), _hit(0.88)]
    with (
        patch("enigma.vault.linker.embed_note", return_value=[0.1] * 768),
        patch("enigma.vault.linker.search", return_value=hits),
        patch("enigma.vault.linker._client", return_value=_llm_client(False)),
    ):
        suggestions = suggest_wikilinks(note)
    assert suggestions == []


def test_suggest_skips_llm_when_validation_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "link_llm_validation", False)
    note = _note()
    hits = [_hit(0.90)]
    client = _llm_client(False)
    with (
        patch("enigma.vault.linker.embed_note", return_value=[0.1] * 768),
        patch("enigma.vault.linker.search", return_value=hits),
        patch("enigma.vault.linker._client", return_value=client),
    ):
        suggestions = suggest_wikilinks(note)
    assert len(suggestions) == 1  # sin validación, el candidato pasa
    client.chat.assert_not_called()


def test_suggest_llm_failure_drops_candidate_conservatively() -> None:
    """Si el LLM devuelve JSON inválido, el candidato se descarta."""
    note = _note()
    bad_client = MagicMock()
    bad_client.chat.return_value = {"message": {"content": "{no es json"}}
    with (
        patch("enigma.vault.linker.embed_note", return_value=[0.1] * 768),
        patch("enigma.vault.linker.search", return_value=[_hit(0.90)]),
        patch("enigma.vault.linker._client", return_value=bad_client),
    ):
        suggestions = suggest_wikilinks(note)
    assert suggestions == []


# ── forma del resultado ─────────────────────────────────────────────────────


def test_suggestions_carry_target_metadata() -> None:
    note = _note()
    target_id = uuid4()
    hits = [_hit(0.91, note_id=target_id, title="Pricing por volumen")]
    with (
        patch("enigma.vault.linker.embed_note", return_value=[0.1] * 768),
        patch("enigma.vault.linker.search", return_value=hits),
        patch("enigma.vault.linker._client", return_value=_llm_client(True)),
    ):
        suggestions = suggest_wikilinks(note)
    assert len(suggestions) == 1
    s = suggestions[0]
    assert isinstance(s, WikilinkSuggestion)
    assert s.target_note_id == target_id
    assert s.target_title == "Pricing por volumen"
    assert s.score == 0.91


def test_suggest_empty_when_no_candidates() -> None:
    note = _note()
    with (
        patch("enigma.vault.linker.embed_note", return_value=[0.1] * 768),
        patch("enigma.vault.linker.search", return_value=[]),
        patch("enigma.vault.linker._client", return_value=_llm_client(True)),
    ):
        assert suggest_wikilinks(note) == []
