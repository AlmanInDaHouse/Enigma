"""Tests unitarios para `enigma.agent.serendipity` (T-406).

Mockean `embed_note`, `search`, `load_all_notes` y el cliente Ollama para
verificar la banda de candidatos, el corte a N sugerencias y el render sin
tocar Qdrant, el Vault ni el LLM real.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from enigma.agent.serendipity import (
    SerendipitySuggestion,
    build_serendipity_index,
    find_serendipity_candidates,
    judge_serendipity,
    render_serendipity_markdown,
)
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


def _llm_client(*, connection: bool, insight: str = "una idea") -> MagicMock:
    client = MagicMock()
    client.chat.return_value = {
        "message": {"content": json.dumps({"connection": connection, "insight": insight})}
    }
    return client


def _suggestion() -> SerendipitySuggestion:
    return SerendipitySuggestion(
        note_a_id=uuid4(),
        note_a_title="A",
        note_a_stem="a-00000000",
        note_b_id=uuid4(),
        note_b_title="B",
        note_b_stem="b-11111111",
        insight="Conectarlas sugiere una analogía útil.",
    )


# ── find_serendipity_candidates ─────────────────────────────────────────────


def test_candidates_keep_only_the_mid_band() -> None:
    """Score en [0.63, 0.74) entra; obvio (≥0.74) y ruido (<0.63) quedan fuera."""
    note, mid, obvious, noise = _note("A"), _note("Media"), _note("Obvia"), _note("Ruido")
    with (
        patch("enigma.agent.serendipity.embed_note", return_value=[0.1] * 768),
        patch(
            "enigma.agent.serendipity.search",
            side_effect=[
                [_hit(mid.id, 0.68), _hit(obvious.id, 0.90), _hit(noise.id, 0.55)],
                [],
                [],
                [],
            ],
        ),
    ):
        candidates = find_serendipity_candidates([note, mid, obvious, noise])
    assert candidates == [frozenset({note.id, mid.id})]


def test_candidates_deduplicates_symmetric_pairs() -> None:
    note_a, note_b = _note("A"), _note("B")
    with (
        patch("enigma.agent.serendipity.embed_note", return_value=[0.1] * 768),
        patch(
            "enigma.agent.serendipity.search",
            side_effect=[[_hit(note_b.id, 0.70)], [_hit(note_a.id, 0.70)]],
        ),
    ):
        candidates = find_serendipity_candidates([note_a, note_b])
    assert candidates == [frozenset({note_a.id, note_b.id})]


def test_candidates_excludes_self_and_unknown() -> None:
    note_a = _note("A")
    ghost = uuid4()
    with (
        patch("enigma.agent.serendipity.embed_note", return_value=[0.1] * 768),
        patch(
            "enigma.agent.serendipity.search",
            side_effect=[[_hit(note_a.id, 0.70), _hit(ghost, 0.70)]],
        ),
    ):
        assert find_serendipity_candidates([note_a]) == []


# ── judge_serendipity ───────────────────────────────────────────────────────


def test_judge_returns_suggestion_when_llm_confirms() -> None:
    note_a, note_b = _note("A"), _note("B")
    with patch(
        "enigma.agent.serendipity._client",
        return_value=_llm_client(connection=True, insight="Analogía."),
    ):
        result = judge_serendipity(note_a, note_b)
    assert result is not None
    assert result.note_a_id == note_a.id
    assert result.insight == "Analogía."


def test_judge_returns_none_when_llm_declines() -> None:
    with patch(
        "enigma.agent.serendipity._client",
        return_value=_llm_client(connection=False),
    ):
        assert judge_serendipity(_note("A"), _note("B")) is None


# ── render_serendipity_markdown ─────────────────────────────────────────────


def test_render_lists_suggestions_with_links() -> None:
    md = render_serendipity_markdown([_suggestion()])
    assert "type: serendipity-index" in md
    assert "suggestion_count: 1" in md
    assert "[[a-00000000|A]]" in md
    assert "[[b-11111111|B]]" in md
    assert "analogía útil" in md


def test_render_empty() -> None:
    md = render_serendipity_markdown([])
    assert "suggestion_count: 0" in md
    assert "No se han encontrado conexiones no obvias" in md


# ── build_serendipity_index ─────────────────────────────────────────────────


def test_build_index_caps_at_max_suggestions(tmp_path: Path) -> None:
    """Con muchos candidatos confirmados, se corta en serendipity_max_suggestions."""
    notes = [_note(f"N{i}") for i in range(12)]
    # 8 pares candidatos; el LLM confirma todos.
    pairs = [frozenset({notes[i].id, notes[i + 1].id}) for i in range(8)]
    with (
        patch("enigma.agent.serendipity.load_all_notes", return_value=notes),
        patch("enigma.agent.serendipity.find_serendipity_candidates", return_value=pairs),
        patch(
            "enigma.agent.serendipity._client",
            return_value=_llm_client(connection=True),
        ),
    ):
        result = build_serendipity_index(vault_path=tmp_path)
    assert len(result.suggestions) == 5  # serendipity_max_suggestions
    assert result.pairs_evaluated == 5  # se detiene al alcanzar el tope


def test_build_index_aggregates_confirmed(tmp_path: Path) -> None:
    note_a, note_b = _note("A"), _note("B")
    pair = frozenset({note_a.id, note_b.id})
    with (
        patch("enigma.agent.serendipity.load_all_notes", return_value=[note_a, note_b]),
        patch("enigma.agent.serendipity.find_serendipity_candidates", return_value=[pair]),
        patch(
            "enigma.agent.serendipity._client",
            return_value=_llm_client(connection=True, insight="Idea."),
        ),
    ):
        result = build_serendipity_index(vault_path=tmp_path)
    assert len(result.suggestions) == 1
    assert result.index_path == tmp_path / "serendipity.md"
    assert result.index_path.exists()


def test_build_index_empty_corpus(tmp_path: Path) -> None:
    with (
        patch("enigma.agent.serendipity.load_all_notes", return_value=[]),
        patch("enigma.agent.serendipity.find_serendipity_candidates", return_value=[]),
    ):
        result = build_serendipity_index(vault_path=tmp_path)
    assert result.suggestions == []
    assert "suggestion_count: 0" in result.index_path.read_text(encoding="utf-8")


def test_build_index_skips_pair_when_judgment_fails(tmp_path: Path) -> None:
    from enigma.agent.serendipity import SerendipityError

    note_a, note_b = _note("A"), _note("B")
    pair = frozenset({note_a.id, note_b.id})
    with (
        patch("enigma.agent.serendipity.load_all_notes", return_value=[note_a, note_b]),
        patch("enigma.agent.serendipity.find_serendipity_candidates", return_value=[pair]),
        patch(
            "enigma.agent.serendipity.judge_serendipity",
            side_effect=SerendipityError("boom"),
        ),
    ):
        result = build_serendipity_index(vault_path=tmp_path)
    assert result.suggestions == []
    assert result.pairs_evaluated == 1
    assert result.index_path.exists()
