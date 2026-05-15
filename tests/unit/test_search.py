"""Tests unitarios para `enigma.search` y el comando `enigma search` (T-301).

Mockean `embed_text` y `search` (Qdrant) para verificar el mapeo
`SearchHit → SearchResult` y la CLI sin tocar Ollama ni Qdrant reales.
"""

from datetime import UTC, datetime
from unittest.mock import patch
from uuid import UUID, uuid4

from typer.testing import CliRunner

from enigma.cli import app
from enigma.search import SearchResult, search_notes
from enigma.vector.qdrant_client import SearchHit

runner = CliRunner()


def _hit(
    score: float,
    *,
    note_id: UUID | None = None,
    title: str = "Vecina",
    payload_extra: dict | None = None,
) -> SearchHit:
    """Construye un `SearchHit` con un payload Qdrant completo por defecto."""
    payload = {
        "title": title,
        "tags": ["padel", "captacion"],
        "call_id": str(uuid4()),
        "created_at": datetime.now(tz=UTC).isoformat(),
        "speakers": ["SPEAKER_00"],
        "status": "draft",
        "content_hash": "a" * 64,
    }
    if payload_extra is not None:
        payload.update(payload_extra)
    return SearchHit(
        note_id=note_id if note_id is not None else uuid4(),
        score=score,
        payload=payload,
    )


# ── search_notes ────────────────────────────────────────────────────────────


def test_search_notes_maps_hits_to_results() -> None:
    note_id = uuid4()
    hits = [_hit(0.91, note_id=note_id, title="Pricing por volumen")]
    with (
        patch("enigma.search.embed_text", return_value=[0.1] * 768),
        patch("enigma.search.search", return_value=hits),
    ):
        results = search_notes("estrategia de pricing")
    assert len(results) == 1
    result = results[0]
    assert isinstance(result, SearchResult)
    assert result.note_id == note_id
    assert result.title == "Pricing por volumen"
    assert result.score == 0.91
    assert result.tags == ["padel", "captacion"]
    assert result.status == "draft"
    assert isinstance(result.call_id, UUID)
    assert isinstance(result.created_at, datetime)


def test_search_notes_passes_top_k() -> None:
    with (
        patch("enigma.search.embed_text", return_value=[0.1] * 768),
        patch("enigma.search.search", return_value=[]) as mock_search,
    ):
        search_notes("query", top_k=12)
    assert mock_search.call_args.kwargs["top_k"] == 12


def test_search_notes_embeds_the_query() -> None:
    with (
        patch("enigma.search.embed_text", return_value=[0.2] * 768) as mock_embed,
        patch("enigma.search.search", return_value=[]),
    ):
        search_notes("clubs de padel")
    mock_embed.assert_called_once_with("clubs de padel")


def test_search_notes_empty_when_no_hits() -> None:
    with (
        patch("enigma.search.embed_text", return_value=[0.1] * 768),
        patch("enigma.search.search", return_value=[]),
    ):
        assert search_notes("nada relevante") == []


def test_search_notes_preserves_qdrant_order() -> None:
    hits = [_hit(0.95, title="A"), _hit(0.80, title="B"), _hit(0.60, title="C")]
    with (
        patch("enigma.search.embed_text", return_value=[0.1] * 768),
        patch("enigma.search.search", return_value=hits),
    ):
        results = search_notes("orden")
    assert [r.title for r in results] == ["A", "B", "C"]


def test_search_notes_handles_partial_payload() -> None:
    """Un payload sin `call_id`/`created_at` no rompe la búsqueda."""
    hit = SearchHit(note_id=uuid4(), score=0.88, payload={"title": "Suelta"})
    with (
        patch("enigma.search.embed_text", return_value=[0.1] * 768),
        patch("enigma.search.search", return_value=[hit]),
    ):
        results = search_notes("payload incompleto")
    assert len(results) == 1
    result = results[0]
    assert result.title == "Suelta"
    assert result.call_id is None
    assert result.created_at is None
    assert result.tags == []
    assert result.status == "draft"


def test_search_notes_handles_malformed_payload_fields() -> None:
    """`call_id`/`created_at` con valores basura caen a `None`, sin excepción."""
    hit = _hit(0.7, payload_extra={"call_id": "no-es-uuid", "created_at": "ayer"})
    with (
        patch("enigma.search.embed_text", return_value=[0.1] * 768),
        patch("enigma.search.search", return_value=[hit]),
    ):
        results = search_notes("basura")
    assert results[0].call_id is None
    assert results[0].created_at is None


# ── enigma search (CLI) ─────────────────────────────────────────────────────


def test_cli_search_shows_results() -> None:
    hits = [_hit(0.91, title="Captacion por club")]
    with (
        patch("enigma.search.embed_text", return_value=[0.1] * 768),
        patch("enigma.search.search", return_value=hits),
    ):
        result = runner.invoke(app, ["search", "como captamos socios"])
    assert result.exit_code == 0
    assert "Captacion por club" in result.output


def test_cli_search_no_results() -> None:
    with (
        patch("enigma.search.embed_text", return_value=[0.1] * 768),
        patch("enigma.search.search", return_value=[]),
    ):
        result = runner.invoke(app, ["search", "tema inexistente"])
    assert result.exit_code == 0
    assert "Sin resultados" in result.output


def test_cli_search_rejects_blank_query() -> None:
    result = runner.invoke(app, ["search", "   "])
    assert result.exit_code != 0


def test_cli_search_top_k_option() -> None:
    with (
        patch("enigma.search.embed_text", return_value=[0.1] * 768),
        patch("enigma.search.search", return_value=[]) as mock_search,
    ):
        result = runner.invoke(app, ["search", "query", "--top-k", "3"])
    assert result.exit_code == 0
    assert mock_search.call_args.kwargs["top_k"] == 3
