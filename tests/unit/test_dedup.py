"""Tests para `enigma.extract.dedup` (T-108)."""

import hashlib
from datetime import UTC, datetime
from uuid import uuid4

from enigma.extract.dedup import dedupe_notes
from enigma.models.note import Note, NoteSource


def _note(title: str, body: str) -> Note:
    """Helper: crea una Note coherente con `content_hash = sha256(body)`."""
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


# ── edge cases ──────────────────────────────────────────────────────────────


def test_empty_input_returns_empty_list() -> None:
    assert dedupe_notes([]) == []


def test_single_note_passes_through_unchanged() -> None:
    n = _note("idea", "cuerpo")
    assert dedupe_notes([n]) == [n]


# ── dedup exacto por content_hash ──────────────────────────────────────────


def test_two_notes_with_identical_body_dedupe_to_one() -> None:
    """Mismo cuerpo → mismo content_hash → se queda la primera."""
    a = _note("Idea A", "Cuerpo idéntico.")
    b = _note("Idea A copia", "Cuerpo idéntico.")
    out = dedupe_notes([a, b])
    assert len(out) == 1
    assert out[0].id == a.id  # se conserva la primera


def test_identical_body_dedup_runs_before_title_dedup() -> None:
    """El paso 1 (hash) atrapa duplicados aunque los títulos sean muy distintos."""
    a = _note("Estrategia padel", "Cuerpo exacto y único.")
    b = _note("Otra cosa completamente diferente", "Cuerpo exacto y único.")
    out = dedupe_notes([a, b])
    assert len(out) == 1


# ── dedup aproximado por título ────────────────────────────────────────────


def test_very_similar_titles_dedupe_to_one() -> None:
    """Títulos casi idénticos (>0.92) se fusionan."""
    a = _note("Estrategia de captación para clubs de padel", "Cuerpo corto.")
    b = _note("Estrategia de captación para clubes de padel", "Cuerpo corto.")
    out = dedupe_notes([a, b])
    assert len(out) == 1


def test_dissimilar_titles_are_kept_separate() -> None:
    """Títulos diferentes (<0.92) son notas distintas."""
    a = _note("Estrategia de captación de clubs", "Cuerpo uno.")
    b = _note("Plan de precios para equipación", "Cuerpo dos.")
    out = dedupe_notes([a, b])
    assert len(out) == 2


def test_in_title_cluster_keeps_longest_body() -> None:
    """Cuando dos títulos similares chocan, gana el cuerpo más largo."""
    short = _note("Captación de padel clubs", "Corto.")
    long = _note("Captación de padel clubs.", "Cuerpo mucho más detallado con datos concretos.")
    out = dedupe_notes([short, long])
    assert len(out) == 1
    assert out[0].body == long.body


def test_title_dedup_is_case_insensitive() -> None:
    a = _note("ESTRATEGIA Padel", "Cuerpo a.")
    b = _note("estrategia padel", "Cuerpo b.")
    out = dedupe_notes([a, b])
    assert len(out) == 1


def test_custom_threshold_below_default_merges_more() -> None:
    """Threshold bajo (0.5) fusiona títulos que el default mantendría separados."""
    a = _note("Estrategia padel", "Cuerpo a.")
    b = _note("Plan padel", "Cuerpo b.")
    out_default = dedupe_notes([a, b])
    out_lax = dedupe_notes([a, b], threshold=0.5)
    assert len(out_default) == 2
    assert len(out_lax) == 1


def test_custom_threshold_above_default_keeps_more() -> None:
    """Threshold alto (1.0) solo fusiona títulos idénticos."""
    a = _note("Estrategia de captación para clubs de padel", "Cuerpo a.")
    b = _note("Estrategia de captación para clubes de padel", "Cuerpo b.")
    # Con threshold=1.0, los acentos/letras distintas mantienen ambas notas.
    out = dedupe_notes([a, b], threshold=1.0)
    assert len(out) == 2


def test_order_is_preserved_across_unique_notes() -> None:
    a = _note("Alpha", "uno")
    b = _note("Beta", "dos")
    c = _note("Gamma", "tres")
    out = dedupe_notes([a, b, c])
    assert [n.title for n in out] == ["Alpha", "Beta", "Gamma"]
