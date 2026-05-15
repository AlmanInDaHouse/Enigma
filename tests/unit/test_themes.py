"""Tests unitarios para `enigma.agent.themes` (T-405).

Mockean `embed_note`, `search`, `load_all_notes` y el cliente Ollama para
verificar el clustering, el filtro de recurrencia y el render sin tocar
Qdrant, el Vault ni el LLM real.
"""

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

from enigma.agent.themes import (
    RecurringTheme,
    ThemeMember,
    ThemesError,
    build_recurring_themes_index,
    cluster_notes,
    name_theme,
    render_themes_markdown,
)
from enigma.models.note import Note, NoteSource
from enigma.vector.qdrant_client import SearchHit


def _note(title: str, *, call_id: UUID | None = None, body: str = "Cuerpo.") -> Note:
    return Note(
        id=uuid4(),
        title=title,
        body=body,
        tags=["t"],
        source=NoteSource(
            call_id=call_id if call_id is not None else uuid4(),
            timestamp_start=0.0,
            timestamp_end=1.0,
        ),
        content_hash=hashlib.sha256(body.encode("utf-8")).hexdigest(),
        extracted_by="qwen2.5:7b",
        created_at=datetime.now(tz=UTC),
    )


def _hit(note_id: UUID, score: float) -> SearchHit:
    return SearchHit(note_id=note_id, score=score, payload={"title": "x"})


def _llm_client(theme: str = "Captación de socios", summary: str = "Un hilo común.") -> MagicMock:
    client = MagicMock()
    client.chat.return_value = {
        "message": {"content": json.dumps({"theme": theme, "summary": summary})}
    }
    return client


# ── cluster_notes ───────────────────────────────────────────────────────────


def test_cluster_merges_transitive_neighbors() -> None:
    """A~B y B~C ⇒ {A, B, C} en un solo cluster (single-linkage)."""
    a, b, c = _note("A"), _note("B"), _note("C")
    # search se llama una vez por nota, en orden: A, B, C.
    with (
        patch("enigma.agent.themes.embed_note", return_value=[0.1] * 768),
        patch(
            "enigma.agent.themes.search",
            side_effect=[[_hit(b.id, 0.9)], [_hit(c.id, 0.9)], []],
        ),
    ):
        clusters = cluster_notes([a, b, c])
    assert len(clusters) == 1
    assert {n.id for n in clusters[0]} == {a.id, b.id, c.id}


def test_cluster_separates_below_threshold() -> None:
    a, b = _note("A"), _note("B")
    with (
        patch("enigma.agent.themes.embed_note", return_value=[0.1] * 768),
        patch(
            "enigma.agent.themes.search",
            side_effect=[[_hit(b.id, 0.40)], [_hit(a.id, 0.40)]],
        ),
    ):
        clusters = cluster_notes([a, b])
    assert len(clusters) == 2


def test_cluster_isolated_note_is_singleton() -> None:
    a = _note("Sola")
    with (
        patch("enigma.agent.themes.embed_note", return_value=[0.1] * 768),
        patch("enigma.agent.themes.search", side_effect=[[]]),
    ):
        clusters = cluster_notes([a])
    assert clusters == [[a]]


# ── name_theme ──────────────────────────────────────────────────────────────


def test_name_theme_builds_recurring_theme() -> None:
    call = uuid4()
    notes = [_note("N1", call_id=call), _note("N2", call_id=uuid4())]
    with patch(
        "enigma.agent.themes._client",
        return_value=_llm_client(theme="Pricing", summary="Sobre precios."),
    ):
        theme = name_theme(notes)
    assert theme.name == "Pricing"
    assert theme.summary == "Sobre precios."
    assert theme.note_count == 2
    assert theme.call_count == 2
    assert len(theme.members) == 2


def test_name_theme_llm_failure_raises() -> None:
    bad = MagicMock()
    bad.chat.return_value = {"message": {"content": "{roto"}}
    with patch("enigma.agent.themes._client", return_value=bad):
        try:
            name_theme([_note("A")])
        except ThemesError:
            pass
        else:
            raise AssertionError("se esperaba ThemesError")


# ── render_themes_markdown ──────────────────────────────────────────────────


def test_render_lists_themes_with_links() -> None:
    theme = RecurringTheme(
        name="Captación",
        summary="Resumen del tema.",
        note_count=3,
        call_count=2,
        members=[ThemeMember(note_id=uuid4(), title="Nota A", stem="nota-a-0001")],
    )
    md = render_themes_markdown([theme])
    assert "type: recurring-themes-index" in md
    assert "theme_count: 1" in md
    assert "## Captación" in md
    assert "[[nota-a-0001|Nota A]]" in md
    assert "3 en 2 llamadas" in md


def test_render_empty() -> None:
    md = render_themes_markdown([])
    assert "theme_count: 0" in md
    assert "No se han detectado ideas recurrentes" in md


# ── build_recurring_themes_index ────────────────────────────────────────────


def test_build_index_keeps_recurring_cluster(tmp_path: Path) -> None:
    """Cluster de 3 notas de 3 llamadas distintas ⇒ idea recurrente."""
    cluster = [_note(f"N{i}", call_id=uuid4()) for i in range(3)]
    with (
        patch("enigma.agent.themes.load_all_notes", return_value=cluster),
        patch("enigma.agent.themes.cluster_notes", return_value=[cluster]),
        patch("enigma.agent.themes._client", return_value=_llm_client()),
    ):
        result = build_recurring_themes_index(vault_path=tmp_path)
    assert len(result.themes) == 1
    assert result.themes[0].call_count == 3
    assert result.index_path == tmp_path / "recurring-themes.md"


def test_build_index_drops_single_call_cluster(tmp_path: Path) -> None:
    """3 notas pero todas de la MISMA llamada ⇒ no es recurrente."""
    one_call = uuid4()
    cluster = [_note(f"N{i}", call_id=one_call) for i in range(3)]
    with (
        patch("enigma.agent.themes.load_all_notes", return_value=cluster),
        patch("enigma.agent.themes.cluster_notes", return_value=[cluster]),
        patch("enigma.agent.themes._client", return_value=_llm_client()),
    ):
        result = build_recurring_themes_index(vault_path=tmp_path)
    assert result.themes == []
    assert result.clusters_found == 1


def test_build_index_drops_small_cluster(tmp_path: Path) -> None:
    """Cluster de 2 notas ⇒ por debajo de recurring_min_notes (3)."""
    cluster = [_note("N1", call_id=uuid4()), _note("N2", call_id=uuid4())]
    with (
        patch("enigma.agent.themes.load_all_notes", return_value=cluster),
        patch("enigma.agent.themes.cluster_notes", return_value=[cluster]),
        patch("enigma.agent.themes._client", return_value=_llm_client()),
    ):
        result = build_recurring_themes_index(vault_path=tmp_path)
    assert result.themes == []


def test_build_index_empty_corpus(tmp_path: Path) -> None:
    with (
        patch("enigma.agent.themes.load_all_notes", return_value=[]),
        patch("enigma.agent.themes.cluster_notes", return_value=[]),
    ):
        result = build_recurring_themes_index(vault_path=tmp_path)
    assert result.themes == []
    assert "theme_count: 0" in result.index_path.read_text(encoding="utf-8")


def test_build_index_skips_cluster_when_naming_fails(tmp_path: Path) -> None:
    cluster = [_note(f"N{i}", call_id=uuid4()) for i in range(3)]
    with (
        patch("enigma.agent.themes.load_all_notes", return_value=cluster),
        patch("enigma.agent.themes.cluster_notes", return_value=[cluster]),
        patch("enigma.agent.themes.name_theme", side_effect=ThemesError("boom")),
    ):
        result = build_recurring_themes_index(vault_path=tmp_path)
    assert result.themes == []
    assert result.index_path.exists()
