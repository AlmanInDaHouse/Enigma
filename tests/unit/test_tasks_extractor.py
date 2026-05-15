"""Tests unitarios para `enigma.agent.tasks_extractor` (T-403).

Mockean `get_connection`, `calls_db.list_calls`, `load_transcript` y el
cliente Ollama para verificar la extracción y el render sin tocar SQLite, el
disco de transcripts ni el LLM real.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch
from uuid import uuid4

from enigma.agent.tasks_extractor import (
    PendingTask,
    TasksError,
    build_task_index,
    extract_tasks_from_call,
    render_tasks_markdown,
)
from enigma.models.call import Call
from enigma.models.transcript import Transcript, TranscriptSegment


def _call(title: str = "Sprint", *, recorded: datetime | None = None) -> Call:
    return Call(
        id=uuid4(),
        content_hash=uuid4().hex + uuid4().hex,
        title=title,
        audio_path=Path("/tmp/audio.wav"),
        duration_seconds=600.0,
        language="es",
        recorded_at=recorded or datetime(2026, 5, 14, 10, 0, tzinfo=UTC),
        ingested_at=datetime.now(tz=UTC),
    )


def _transcript(call_id: object, *, empty: bool = False) -> Transcript:
    segments = (
        []
        if empty
        else [TranscriptSegment(start=0.0, end=5.0, text="Hay que preparar la campaña.")]
    )
    return Transcript(
        call_id=call_id,  # type: ignore[arg-type]
        model="faster-whisper:large-v3",
        language="es",
        segments=segments,
        created_at=datetime.now(tz=UTC),
    )


def _llm_client(tasks: list[dict[str, object]]) -> MagicMock:
    """Cliente Ollama falso cuyo `.chat` devuelve `{"tasks": [...]}`."""
    client = MagicMock()
    client.chat.return_value = {"message": {"content": json.dumps({"tasks": tasks})}}
    return client


def _task(
    statement: str,
    *,
    recorded: datetime,
    assignee: str | None = None,
    title: str = "Llamada",
) -> PendingTask:
    return PendingTask(
        statement=statement,
        assignee=assignee,
        call_id=uuid4(),
        call_title=title,
        recorded_at=recorded,
        call_index_stem=f"{recorded:%Y-%m-%d}-llamada-abcdef12",
    )


# ── extract_tasks_from_call ─────────────────────────────────────────────────


def test_extract_maps_tasks_with_assignee() -> None:
    call = _call()
    with patch(
        "enigma.agent.tasks_extractor._client",
        return_value=_llm_client(
            [
                {"statement": "Preparar campaña", "assignee": "Manuel"},
                {"statement": "Reservar pista", "assignee": None},
            ]
        ),
    ):
        tasks = extract_tasks_from_call(call, _transcript(call.id))
    assert [t.statement for t in tasks] == ["Preparar campaña", "Reservar pista"]
    assert tasks[0].assignee == "Manuel"
    assert tasks[1].assignee is None
    assert all(t.call_id == call.id for t in tasks)


def test_extract_empty_transcript_skips_llm() -> None:
    call = _call()
    client = _llm_client([{"statement": "no debería", "assignee": None}])
    with patch("enigma.agent.tasks_extractor._client", return_value=client):
        tasks = extract_tasks_from_call(call, _transcript(call.id, empty=True))
    assert tasks == []
    client.chat.assert_not_called()


def test_extract_blank_assignee_becomes_none() -> None:
    call = _call()
    with patch(
        "enigma.agent.tasks_extractor._client",
        return_value=_llm_client([{"statement": "Tarea", "assignee": "   "}]),
    ):
        tasks = extract_tasks_from_call(call, _transcript(call.id))
    assert tasks[0].assignee is None


def test_extract_drops_blank_statements() -> None:
    call = _call()
    with patch(
        "enigma.agent.tasks_extractor._client",
        return_value=_llm_client(
            [{"statement": "Tarea real", "assignee": None}, {"statement": "  ", "assignee": None}]
        ),
    ):
        tasks = extract_tasks_from_call(call, _transcript(call.id))
    assert len(tasks) == 1


# ── render_tasks_markdown ───────────────────────────────────────────────────


def test_render_groups_and_orders_reverse_chronologically() -> None:
    old = _task("Vieja", recorded=datetime(2026, 1, 1, tzinfo=UTC))
    recent = _task("Reciente", recorded=datetime(2026, 5, 1, tzinfo=UTC))
    md = render_tasks_markdown([old, recent])
    assert md.index("Reciente") < md.index("Vieja")
    assert "type: task-index" in md
    assert "task_count: 2" in md


def test_render_task_is_a_checkbox_with_assignee() -> None:
    task = _task("Preparar campaña", recorded=datetime(2026, 5, 1, tzinfo=UTC), assignee="Manuel")
    md = render_tasks_markdown([task])
    assert "- [ ] Preparar campaña — _Manuel_" in md


def test_render_task_without_assignee() -> None:
    task = _task("Reservar pista", recorded=datetime(2026, 5, 1, tzinfo=UTC))
    md = render_tasks_markdown([task])
    assert "- [ ] Reservar pista\n" in md
    assert "_None_" not in md


def test_render_empty_corpus() -> None:
    md = render_tasks_markdown([])
    assert "type: task-index" in md
    assert "task_count: 0" in md
    assert "No hay tareas pendientes" in md


# ── build_task_index ────────────────────────────────────────────────────────


def test_build_index_aggregates_corpus(tmp_path: Path) -> None:
    call_a = _call("Llamada A", recorded=datetime(2026, 5, 1, 9, 0, tzinfo=UTC))
    call_b = _call("Llamada B", recorded=datetime(2026, 5, 2, 9, 0, tzinfo=UTC))
    transcripts = {call_a.id: _transcript(call_a.id), call_b.id: _transcript(call_b.id)}

    with (
        patch("enigma.agent.tasks_extractor.get_connection"),
        patch("enigma.agent.tasks_extractor.calls_db.list_calls", return_value=[call_a, call_b]),
        patch(
            "enigma.agent.tasks_extractor.load_transcript",
            side_effect=lambda cid: transcripts.get(cid),
        ),
        patch(
            "enigma.agent.tasks_extractor._client",
            return_value=_llm_client([{"statement": "Una tarea", "assignee": "Ana"}]),
        ),
    ):
        result = build_task_index(vault_path=tmp_path)

    assert result.calls_scanned == 2
    assert result.calls_with_tasks == 2
    assert len(result.tasks) == 2
    assert result.index_path == tmp_path / "tasks.md"
    assert result.index_path.exists()


def test_build_index_skips_calls_without_transcript(tmp_path: Path) -> None:
    call_a = _call("Con transcript")
    call_b = _call("Sin transcript")
    with (
        patch("enigma.agent.tasks_extractor.get_connection"),
        patch("enigma.agent.tasks_extractor.calls_db.list_calls", return_value=[call_a, call_b]),
        patch(
            "enigma.agent.tasks_extractor.load_transcript",
            side_effect=lambda cid: _transcript(cid) if cid == call_a.id else None,
        ),
        patch(
            "enigma.agent.tasks_extractor._client",
            return_value=_llm_client([{"statement": "T", "assignee": None}]),
        ),
    ):
        result = build_task_index(vault_path=tmp_path)
    assert result.calls_scanned == 1


def test_build_index_continues_when_a_call_fails(tmp_path: Path) -> None:
    """Si la extracción de una llamada falla, el índice se construye igual."""
    call_ok = _call("OK")
    call_bad = _call("Falla")
    with (
        patch("enigma.agent.tasks_extractor.get_connection"),
        patch(
            "enigma.agent.tasks_extractor.calls_db.list_calls",
            return_value=[call_ok, call_bad],
        ),
        patch("enigma.agent.tasks_extractor.load_transcript", side_effect=_transcript),
        patch(
            "enigma.agent.tasks_extractor.extract_tasks_from_call",
            side_effect=[
                [_task("Tarea válida", recorded=call_ok.recorded_at)],
                TasksError("boom"),
            ],
        ),
    ):
        result = build_task_index(vault_path=tmp_path)
    assert result.calls_scanned == 2
    assert len(result.tasks) == 1
    assert result.index_path.exists()


def test_build_index_empty_corpus_writes_empty_index(tmp_path: Path) -> None:
    with (
        patch("enigma.agent.tasks_extractor.get_connection"),
        patch("enigma.agent.tasks_extractor.calls_db.list_calls", return_value=[]),
    ):
        result = build_task_index(vault_path=tmp_path)
    assert result.tasks == []
    assert result.index_path.exists()
    assert "task_count: 0" in result.index_path.read_text(encoding="utf-8")
