"""Tests unitarios para `enigma.agent.contradictions` (T-404).

Mockean `embed_note`, `search`, `load_all_notes` y el cliente Ollama para
verificar la generación de pares candidatos, el juicio y el render sin tocar
Qdrant, el Vault ni el LLM real.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from enigma.agent.contradictions import (
    Contradiction,
    build_contradiction_index,
    find_contradiction_candidates,
    judge_contradiction,
    render_contradictions_markdown,
)
from enigma.config import settings
from enigma.models.note import Note, NoteSource
from enigma.vector.qdrant_client import SearchHit


def _note(title: str = "Idea", body: str = "Cuerpo de la nota.") -> Note:
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


def _hit(note_id: UUID, score: float) -> SearchHit:
    return SearchHit(note_id=note_id, score=score, payload={"title": "x"})


def _llm_client(*, contradiction: bool, explanation: str = "porque sí") -> MagicMock:
    client = MagicMock()
    client.chat.return_value = {
        "message": {
            "content": json.dumps({"contradiction": contradiction, "explanation": explanation})
        }
    }
    return client


def _contradiction() -> Contradiction:
    return Contradiction(
        note_a_id=uuid4(),
        note_a_title="A",
        note_a_stem="a-00000000",
        note_b_id=uuid4(),
        note_b_title="B",
        note_b_stem="b-11111111",
        explanation="Una dice 100€, la otra 500€.",
    )


# ── find_contradiction_candidates ───────────────────────────────────────────


def test_candidates_deduplicates_symmetric_pairs() -> None:
    note_a, note_b = _note("A"), _note("B")
    # A ve a B como vecino y B ve a A: debe salir UN solo par.
    # `search` se llama una vez por nota, en orden: side_effect por posición.
    with (
        patch("enigma.agent.contradictions.embed_note", return_value=[0.1] * 768),
        patch(
            "enigma.agent.contradictions.search",
            side_effect=[[_hit(note_b.id, 0.9)], [_hit(note_a.id, 0.9)]],
        ),
    ):
        candidates = find_contradiction_candidates([note_a, note_b])
    assert candidates == {frozenset({note_a.id, note_b.id})}


def test_candidates_filters_below_threshold() -> None:
    note_a, note_b = _note("A"), _note("B")
    with (
        patch("enigma.agent.contradictions.embed_note", return_value=[0.1] * 768),
        patch(
            "enigma.agent.contradictions.search",
            side_effect=[[_hit(note_b.id, 0.50)], [_hit(note_a.id, 0.50)]],
        ),
    ):
        candidates = find_contradiction_candidates([note_a, note_b])
    assert candidates == set()


def test_candidates_excludes_self_and_unknown_hits() -> None:
    note_a = _note("A")
    ghost = uuid4()  # un hit que no está entre las notas dadas
    with (
        patch("enigma.agent.contradictions.embed_note", return_value=[0.1] * 768),
        patch(
            "enigma.agent.contradictions.search",
            side_effect=[[_hit(note_a.id, 0.99), _hit(ghost, 0.95)]],
        ),
    ):
        candidates = find_contradiction_candidates([note_a])
    assert candidates == set()


# ── judge_contradiction ─────────────────────────────────────────────────────


def test_judge_returns_contradiction_when_llm_says_true() -> None:
    note_a, note_b = _note("Precio A"), _note("Precio B")
    with patch(
        "enigma.agent.contradictions._client",
        return_value=_llm_client(contradiction=True, explanation="Precios opuestos."),
    ):
        result = judge_contradiction(note_a, note_b)
    assert result is not None
    assert result.note_a_id == note_a.id
    assert result.note_b_id == note_b.id
    assert result.explanation == "Precios opuestos."


def test_judge_returns_none_when_llm_says_false() -> None:
    with patch(
        "enigma.agent.contradictions._client",
        return_value=_llm_client(contradiction=False),
    ):
        assert judge_contradiction(_note("A"), _note("B")) is None


# ── render_contradictions_markdown ──────────────────────────────────────────


def test_render_lists_contradictions_with_links() -> None:
    md = render_contradictions_markdown([_contradiction()])
    assert "type: contradiction-index" in md
    assert "contradiction_count: 1" in md
    assert "[[a-00000000|A]]" in md
    assert "[[b-11111111|B]]" in md
    assert "Una dice 100€, la otra 500€." in md


def test_render_empty() -> None:
    md = render_contradictions_markdown([])
    assert "contradiction_count: 0" in md
    assert "No se han detectado contradicciones" in md


# ── build_contradiction_index ───────────────────────────────────────────────


def test_build_index_aggregates_confirmed_contradictions(tmp_path: Path) -> None:
    note_a, note_b, note_c = _note("A"), _note("B"), _note("C")
    pair_ab = frozenset({note_a.id, note_b.id})
    pair_ac = frozenset({note_a.id, note_c.id})

    def _judge(na: Note, nb: Note, *, model: object = None) -> Contradiction | None:
        # Solo el par (A,B) es contradicción.
        if {na.id, nb.id} == set(pair_ab):
            return Contradiction(
                note_a_id=na.id,
                note_a_title=na.title,
                note_a_stem="a",
                note_b_id=nb.id,
                note_b_title=nb.title,
                note_b_stem="b",
                explanation="conflicto",
            )
        return None

    with (
        patch(
            "enigma.agent.contradictions.load_all_notes",
            return_value=[note_a, note_b, note_c],
        ),
        patch(
            "enigma.agent.contradictions.find_contradiction_candidates",
            return_value={pair_ab, pair_ac},
        ),
        patch("enigma.agent.contradictions.judge_contradiction", side_effect=_judge),
    ):
        result = build_contradiction_index(vault_path=tmp_path)

    assert result.notes_scanned == 3
    assert result.pairs_evaluated == 2
    assert len(result.contradictions) == 1
    assert result.index_path == tmp_path / "contradictions.md"
    assert result.index_path.exists()


def test_build_index_empty_corpus(tmp_path: Path) -> None:
    with (
        patch("enigma.agent.contradictions.load_all_notes", return_value=[]),
        patch("enigma.agent.contradictions.find_contradiction_candidates", return_value=set()),
    ):
        result = build_contradiction_index(vault_path=tmp_path)
    assert result.contradictions == []
    assert "contradiction_count: 0" in result.index_path.read_text(encoding="utf-8")


def test_build_index_skips_pair_when_judgment_fails(tmp_path: Path) -> None:
    from enigma.agent.contradictions import ContradictionError

    note_a, note_b = _note("A"), _note("B")
    pair = frozenset({note_a.id, note_b.id})
    with (
        patch("enigma.agent.contradictions.load_all_notes", return_value=[note_a, note_b]),
        patch(
            "enigma.agent.contradictions.find_contradiction_candidates",
            return_value={pair},
        ),
        patch(
            "enigma.agent.contradictions.judge_contradiction",
            side_effect=ContradictionError("boom"),
        ),
    ):
        result = build_contradiction_index(vault_path=tmp_path)
    assert result.pairs_evaluated == 1
    assert result.contradictions == []
    assert result.index_path.exists()


def test_threshold_setting_is_respected() -> None:
    """Sanity-check del default del umbral, por si cambia sin querer."""
    assert settings.contradiction_similarity_threshold == 0.80
