"""Tests para `enigma.extract.chunker` (T-106)."""

from datetime import UTC, datetime
from itertools import pairwise
from uuid import uuid4

import pytest
from pydantic import ValidationError

from enigma.extract.chunker import (
    TranscriptChunk,
    chunk_transcript,
    count_tokens,
)
from enigma.models.transcript import Transcript, TranscriptSegment


def _make_transcript(segments: list[TranscriptSegment]) -> Transcript:
    return Transcript(
        call_id=uuid4(),
        model="faster-whisper:tiny",
        created_at=datetime.now(tz=UTC),
        segments=segments,
    )


def _segment(
    start: float, text: str, *, duration: float = 1.0, speaker: str | None = None
) -> TranscriptSegment:
    return TranscriptSegment(
        start=start,
        end=start + duration,
        text=text,
        speaker=speaker,
    )


# ── count_tokens ────────────────────────────────────────────────────────────


def test_count_tokens_returns_zero_for_empty_string() -> None:
    assert count_tokens("") == 0


def test_count_tokens_grows_with_input() -> None:
    short = count_tokens("hola")
    longer = count_tokens("hola mundo de pruebas para enigma")
    assert longer > short


# ── chunk_transcript: edge cases ────────────────────────────────────────────


def test_empty_transcript_returns_no_chunks() -> None:
    t = _make_transcript([])
    assert chunk_transcript(t) == []


def test_single_short_segment_returns_one_chunk() -> None:
    t = _make_transcript([_segment(0.0, "hola mundo", duration=1.0)])
    chunks = chunk_transcript(t, chunk_tokens=100, overlap_tokens=20)
    assert len(chunks) == 1
    assert chunks[0].segment_start_index == 0
    assert chunks[0].segment_end_index == 0
    assert chunks[0].timestamp_start == 0.0
    assert chunks[0].timestamp_end == 1.0
    assert "hola mundo" in chunks[0].text


def test_single_oversized_segment_still_returns_one_chunk() -> None:
    """Un segmento que excede `chunk_tokens` no se trocea (preserva timestamps)."""
    huge_text = "palabra " * 500  # ~600+ tokens
    t = _make_transcript([_segment(0.0, huge_text, duration=10.0)])
    chunks = chunk_transcript(t, chunk_tokens=50, overlap_tokens=10)
    assert len(chunks) == 1
    assert chunks[0].token_count >= 50


def test_overlap_must_be_smaller_than_chunk_tokens() -> None:
    t = _make_transcript([_segment(0.0, "x", duration=0.5)])
    with pytest.raises(ValueError, match="overlap_tokens"):
        chunk_transcript(t, chunk_tokens=100, overlap_tokens=100)


# ── chunk_transcript: splitting behaviour ───────────────────────────────────


def test_splits_when_total_tokens_exceed_limit() -> None:
    """Con 10 segmentos de ~20 tokens cada uno y chunk_tokens=50, salen >=4 chunks."""
    segs = [
        _segment(float(i), "una frase mas o menos de veinte tokens en español unica " + str(i))
        for i in range(10)
    ]
    t = _make_transcript(segs)
    chunks = chunk_transcript(t, chunk_tokens=50, overlap_tokens=10)
    assert len(chunks) >= 2
    # Cada chunk respeta el límite (excepto si un segmento aislado lo supera).
    for c in chunks:
        if c.segment_end_index > c.segment_start_index:
            assert c.token_count <= 50 + 20  # margen por el último segmento añadido


def test_chunks_cover_all_segments() -> None:
    segs = [_segment(float(i), f"texto numero {i}") for i in range(20)]
    t = _make_transcript(segs)
    chunks = chunk_transcript(t, chunk_tokens=30, overlap_tokens=5)
    # El primer chunk empieza en 0; el último termina en len(segs)-1.
    assert chunks[0].segment_start_index == 0
    assert chunks[-1].segment_end_index == 19


def test_consecutive_chunks_overlap_correctly() -> None:
    """Los chunks consecutivos comparten segmentos cuando overlap > 0."""
    segs = [_segment(float(i), f"texto suficiente largo numero {i}") for i in range(20)]
    t = _make_transcript(segs)
    chunks = chunk_transcript(t, chunk_tokens=40, overlap_tokens=15)
    assert len(chunks) >= 2
    # El segundo chunk arranca antes (o igual) que donde terminó el primero.
    assert chunks[1].segment_start_index <= chunks[0].segment_end_index


def test_chunks_make_progress_even_with_overlap() -> None:
    """Cada chunk avanza al menos un segmento aunque overlap sea grande."""
    segs = [_segment(float(i), f"frase {i}") for i in range(10)]
    t = _make_transcript(segs)
    chunks = chunk_transcript(t, chunk_tokens=30, overlap_tokens=25)
    for prev, nxt in pairwise(chunks):
        assert nxt.segment_start_index > prev.segment_start_index


def test_speakers_are_inlined_in_chunk_text() -> None:
    t = _make_transcript(
        [
            _segment(0.0, "hola", speaker="SPEAKER_00"),
            _segment(1.0, "que tal", speaker="SPEAKER_01"),
        ]
    )
    chunks = chunk_transcript(t, chunk_tokens=200, overlap_tokens=20)
    assert "[SPEAKER_00] hola" in chunks[0].text
    assert "[SPEAKER_01] que tal" in chunks[0].text


def test_chunks_are_pydantic_models_with_validation() -> None:
    """`TranscriptChunk` rechaza valores negativos en timestamps."""
    with pytest.raises(ValidationError):
        TranscriptChunk(
            text="x",
            timestamp_start=-1.0,
            timestamp_end=0.0,
            segment_start_index=0,
            segment_end_index=0,
            token_count=1,
        )


# ── acceptance criterion: 10k-token transcript divides correctly ────────────


def test_10k_token_transcript_divides_into_multiple_chunks() -> None:
    """Aceptación T-106: un transcript de ~10k tokens se divide correctamente."""
    # Construimos segmentos cuyo total estimado supera 10k tokens.
    # "una frase de ejemplo con varias palabras y conceptos distintos uno dos tres"
    # ~15 tokens; 700 segmentos ~= 10500 tokens.
    base_text = "una frase de ejemplo con varias palabras y conceptos distintos uno dos tres"
    segs = [_segment(float(i), base_text) for i in range(700)]
    t = _make_transcript(segs)

    chunks = chunk_transcript(t, chunk_tokens=1500, overlap_tokens=200)

    # Hay múltiples chunks.
    assert len(chunks) >= 5
    # Cubren todo el transcript.
    assert chunks[0].segment_start_index == 0
    assert chunks[-1].segment_end_index == 699
    # Ningún chunk excede dramáticamente chunk_tokens (margen 50% por el último
    # segmento añadido completo).
    for c in chunks:
        assert c.token_count <= 1500 * 1.5
    # Consecutive chunks overlap.
    for prev, nxt in pairwise(chunks):
        assert nxt.segment_start_index <= prev.segment_end_index
