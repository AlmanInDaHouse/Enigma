"""Tests para `enigma.vault.frontmatter` (T-109)."""

from datetime import UTC, datetime
from uuid import uuid4

import frontmatter as fm
import yaml

from enigma.models.note import Note, NoteSource
from enigma.vault.frontmatter import (
    build_frontmatter_dict,
    render_frontmatter_yaml,
    render_note_markdown,
)


def _note(
    *,
    title: str = "Estrategia de captación para clubs de padel",
    body: str = "Los clubs de padel representan un nicho con alta densidad y baja saturación.",
    tags: list[str] | None = None,
    speakers: list[str] | None = None,
    status: str = "draft",
) -> Note:
    return Note(
        id=uuid4(),
        title=title,
        body=body,
        tags=tags if tags is not None else ["estrategia", "padel"],
        source=NoteSource(
            call_id=uuid4(),
            timestamp_start=412.5,
            timestamp_end=478.2,
            speakers=speakers if speakers is not None else ["Manuel"],
        ),
        content_hash="a" * 64,
        status=status,  # type: ignore[arg-type]
        extracted_by="qwen2.5:7b",
        created_at=datetime(2026, 5, 14, 18, 32, tzinfo=UTC),
    )


# ── build_frontmatter_dict ──────────────────────────────────────────────────


def test_frontmatter_dict_has_all_required_keys() -> None:
    d = build_frontmatter_dict(_note())
    for key in (
        "id",
        "title",
        "created_at",
        "source",
        "tags",
        "content_hash",
        "status",
        "extracted_by",
    ):
        assert key in d


def test_frontmatter_dict_keys_appear_in_canonical_order() -> None:
    d = build_frontmatter_dict(_note())
    assert list(d.keys()) == [
        "id",
        "title",
        "created_at",
        "source",
        "tags",
        "content_hash",
        "status",
        "extracted_by",
    ]


def test_frontmatter_dict_serializes_uuid_as_string() -> None:
    d = build_frontmatter_dict(_note())
    assert isinstance(d["id"], str)
    assert isinstance(d["source"]["call_id"], str)


def test_frontmatter_dict_serializes_datetime_as_iso() -> None:
    d = build_frontmatter_dict(_note())
    assert d["created_at"].startswith("2026-05-14T18:32:00")


def test_frontmatter_dict_source_has_required_subfields() -> None:
    d = build_frontmatter_dict(_note())
    for key in ("call_id", "timestamp_start", "timestamp_end", "speakers"):
        assert key in d["source"]


# ── render_frontmatter_yaml ─────────────────────────────────────────────────


def test_yaml_block_is_valid_yaml() -> None:
    yaml_text = render_frontmatter_yaml(_note())
    parsed = yaml.safe_load(yaml_text)
    assert parsed["title"] == "Estrategia de captación para clubs de padel"
    assert parsed["status"] == "draft"


def test_yaml_block_preserves_key_order_textually() -> None:
    yaml_text = render_frontmatter_yaml(_note())
    pos_id = yaml_text.index("id:")
    pos_title = yaml_text.index("title:")
    pos_created = yaml_text.index("created_at:")
    pos_source = yaml_text.index("source:")
    assert pos_id < pos_title < pos_created < pos_source


def test_yaml_block_supports_non_ascii_in_title() -> None:
    """Acentos y caracteres especiales se preservan sin escapes raros."""
    yaml_text = render_frontmatter_yaml(_note(title="Captación rápida — añadir clubs ñ"))
    parsed = yaml.safe_load(yaml_text)
    assert parsed["title"] == "Captación rápida — añadir clubs ñ"


# ── render_note_markdown ────────────────────────────────────────────────────


def test_markdown_has_three_sections() -> None:
    md = render_note_markdown(_note())
    assert md.startswith("---\n")
    assert "\n---\n\n# " in md  # cabecera de título tras el frontmatter
    assert "## Origen" in md


def test_markdown_body_is_present() -> None:
    body = "Cuerpo único de la idea atómica."
    md = render_note_markdown(_note(body=body))
    assert body in md


def test_markdown_origin_section_contains_timestamps() -> None:
    md = render_note_markdown(_note())
    assert "412.5" in md
    assert "478.2" in md


def test_markdown_is_parseable_by_python_frontmatter() -> None:
    """python-frontmatter (lector externo) debe parsear nuestro output sin errores."""
    md = render_note_markdown(_note())
    post = fm.loads(md)
    assert post.metadata["title"] == "Estrategia de captación para clubs de padel"
    assert "padel" in post.content


def test_markdown_round_trips_required_yaml_fields() -> None:
    md = render_note_markdown(_note())
    meta = fm.loads(md).metadata
    for key in (
        "id",
        "title",
        "created_at",
        "source",
        "tags",
        "content_hash",
        "status",
        "extracted_by",
    ):
        assert key in meta


# ── sección ## Conexiones (wikilinks, T-206) ────────────────────────────────


def test_markdown_without_wikilinks_has_no_conexiones() -> None:
    md = render_note_markdown(_note())
    assert "## Conexiones" not in md


def test_markdown_empty_wikilinks_list_has_no_conexiones() -> None:
    md = render_note_markdown(_note(), wikilinks=[])
    assert "## Conexiones" not in md


def test_markdown_with_wikilinks_adds_conexiones_section() -> None:
    md = render_note_markdown(_note(), wikilinks=["[[a-1234|Nota A]]", "[[b-5678|Nota B]]"])
    assert "## Conexiones" in md
    assert "- [[a-1234|Nota A]]" in md
    assert "- [[b-5678|Nota B]]" in md


def test_markdown_conexiones_appears_before_origen() -> None:
    md = render_note_markdown(_note(), wikilinks=["[[a-1234|Nota A]]"])
    assert md.index("## Conexiones") < md.index("## Origen")
