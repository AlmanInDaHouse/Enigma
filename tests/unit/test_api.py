"""Tests para la API REST de Enigma (T-305).

Usan `TestClient` de FastAPI y mockean `answer_question` para verificar el
contrato del endpoint sin tocar el pipeline RAG real.
"""

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import Mock, patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from enigma.agent.rag import Citation, RagAnswer, RagError
from enigma.api import app
from enigma.cli import app as cli_app
from enigma.config import settings
from enigma.models.call import Call
from enigma.search import SearchResult
from enigma.stats import ActivityStats, CorpusStats, EnigmaStats, HealthProbe
from enigma.vault.reader import NoteSummary
from enigma.vector.qdrant_client import VectorStoreUnavailableError

client = TestClient(app)
runner = CliRunner()


def _rag_answer() -> RagAnswer:
    note_id = uuid4()
    return RagAnswer(
        question="¿Cómo captamos socios?",
        answer=(
            "Captamos socios por densidad de clubs [[estrategia-padel-abc12345|Estrategia padel]]."
        ),
        citations=[
            Citation(note_id=note_id, title="Estrategia padel", stem="estrategia-padel-abc12345"),
        ],
        sources=[
            SearchResult(
                note_id=note_id,
                title="Estrategia padel",
                score=0.91,
                tags=["padel"],
                status="draft",
                call_id=uuid4(),
                created_at=datetime.now(tz=UTC),
            ),
        ],
    )


# ── /health ─────────────────────────────────────────────────────────────────


def test_health_returns_ok() -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


# ── POST /ask ────────────────────────────────────────────────────────────────


def test_ask_returns_answer_and_citations() -> None:
    with patch("enigma.api.answer_question", return_value=_rag_answer()) as mock_answer:
        response = client.post("/ask", json={"question": "¿Cómo captamos socios?"})
    assert response.status_code == 200
    body = response.json()
    assert body["answer"].startswith("Captamos socios")
    assert len(body["citations"]) == 1
    assert body["citations"][0]["stem"] == "estrategia-padel-abc12345"
    assert len(body["sources"]) == 1
    mock_answer.assert_called_once()


def test_ask_propagates_top_k_and_rerank() -> None:
    with patch("enigma.api.answer_question", return_value=_rag_answer()) as mock_answer:
        response = client.post(
            "/ask",
            json={"question": "pregunta", "top_k": 9, "rerank": True},
        )
    assert response.status_code == 200
    kwargs = mock_answer.call_args.kwargs
    assert kwargs["top_k"] == 9
    assert kwargs["rerank"] is True


def test_ask_rag_error_returns_503() -> None:
    with patch("enigma.api.answer_question", side_effect=RagError("LLM caído")):
        response = client.post("/ask", json={"question": "pregunta"})
    assert response.status_code == 503
    assert "LLM caído" in response.json()["detail"]


def test_ask_vector_store_down_returns_503_with_actionable_detail() -> None:
    """Qdrant caído → 503 entendible, no un 500 opaco (T-701)."""
    error = VectorStoreUnavailableError(
        "La base vectorial no responde. Arranca Qdrant: docker compose up -d qdrant",
    )
    with patch("enigma.api.answer_question", side_effect=error):
        response = client.post("/ask", json={"question": "pregunta"})
    assert response.status_code == 503
    assert "Qdrant" in response.json()["detail"]


def test_ask_unexpected_error_returns_503_not_500() -> None:
    """Cualquier fallo inesperado se traduce a un 503 con JSON, nunca un 500."""
    with patch("enigma.api.answer_question", side_effect=RuntimeError("boom")):
        response = client.post("/ask", json={"question": "pregunta"})
    assert response.status_code == 503
    assert response.json()["detail"]  # cuerpo JSON con mensaje, no texto plano


def test_ask_blank_question_returns_422() -> None:
    response = client.post("/ask", json={"question": "   "})
    assert response.status_code == 422


def test_ask_missing_question_returns_422() -> None:
    response = client.post("/ask", json={"top_k": 5})
    assert response.status_code == 422


def test_ask_rejects_unknown_field() -> None:
    response = client.post("/ask", json={"question": "p", "unexpected": 1})
    assert response.status_code == 422


def test_ask_rejects_top_k_below_one() -> None:
    response = client.post("/ask", json={"question": "p", "top_k": 0})
    assert response.status_code == 422


# ── GET / (interfaz web) ─────────────────────────────────────────────────────


def test_index_serves_html() -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Enigma" in response.text


def test_static_assets_are_served() -> None:
    for asset in ("/static/style.css", "/static/app.js"):
        response = client.get(asset)
        assert response.status_code == 200


# ── GET /stats ───────────────────────────────────────────────────────────────


def _stats() -> EnigmaStats:
    return EnigmaStats(
        corpus=CorpusStats(
            total_calls=4,
            calls_by_status={"done": 4},
            total_notes=37,
            notes_by_status={"draft": 30, "validated": 7},
            orphan_notes=5,
            qdrant_vectors=37,
            total_audio_hours=2.5,
            avg_notes_per_call=9.2,
        ),
        activity=ActivityStats(calls_last_7d=2, calls_last_30d=4, notes_per_day={"2026-05-16": 4}),
        health=HealthProbe(qdrant_ok=True, ollama_ok=True, embed_latency_ms=48.0),
    )


def test_stats_returns_metrics() -> None:
    with patch("enigma.api.gather_stats", return_value=_stats()):
        response = client.get("/stats")
    assert response.status_code == 200
    body = response.json()
    assert body["corpus"]["total_notes"] == 37
    assert body["health"]["qdrant_ok"] is True


# ── GET /search ──────────────────────────────────────────────────────────────


def test_search_returns_results() -> None:
    hits = [
        SearchResult(
            note_id=uuid4(),
            title="Estrategia padel",
            score=0.91,
            tags=["padel"],
            status="draft",
            call_id=uuid4(),
            created_at=datetime.now(tz=UTC),
        ),
    ]
    with patch("enigma.api.search_notes", return_value=hits) as mock_search:
        response = client.get("/search", params={"q": "padel", "top_k": 8})
    assert response.status_code == 200
    assert response.json()[0]["title"] == "Estrategia padel"
    assert mock_search.call_args.kwargs["top_k"] == 8


def test_search_blank_query_returns_422() -> None:
    response = client.get("/search", params={"q": "   "})
    assert response.status_code == 422


def test_search_missing_query_returns_422() -> None:
    response = client.get("/search")
    assert response.status_code == 422


def test_search_vector_store_down_returns_503() -> None:
    """Qdrant caído → `/search` responde 503, no un 500 opaco (T-701)."""
    error = VectorStoreUnavailableError("La base vectorial no responde.")
    with patch("enigma.api.search_notes", side_effect=error):
        response = client.get("/search", params={"q": "padel"})
    assert response.status_code == 503
    assert response.json()["detail"]


# ── GET /channels ────────────────────────────────────────────────────────────


def test_channels_lists_fixed_channels() -> None:
    response = client.get("/channels")
    assert response.status_code == 200
    assert "general" in response.json()


# ── GET /calls ───────────────────────────────────────────────────────────────


def _call(title: str = "Reunión", status: str = "done") -> Call:
    now = datetime.now(tz=UTC)
    return Call(
        id=uuid4(),
        content_hash=uuid4().hex + uuid4().hex,
        title=title,
        audio_path=Path("/tmp/a.webm"),
        duration_seconds=900.0,
        language="es",
        recorded_at=now,
        ingested_at=now,
        status=status,  # type: ignore[arg-type]
    )


def test_calls_lists_recent() -> None:
    with patch("enigma.api.calls_db.list_calls", return_value=[_call("Daily", "transcribing")]):
        response = client.get("/calls")
    assert response.status_code == 200
    body = response.json()
    assert body[0]["title"] == "Daily"
    assert body[0]["status"] == "transcribing"


# ── POST /calls/upload ───────────────────────────────────────────────────────


def test_upload_call_runs_full_loop_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Subir una grabación encadena ingest → reindex → summarize (T-702)."""
    monkeypatch.setattr(settings, "enigma_data_path", tmp_path)
    call = _call("Reunión semanal")
    with (
        patch("enigma.api.ingest_audio", return_value=Mock(call=call)) as mock_ingest,
        patch("enigma.api.reindex_vault") as mock_reindex,
        patch("enigma.api.summarize_call") as mock_summarize,
    ):
        response = client.post(
            "/calls/upload",
            params={"title": "Reunión semanal"},
            content=b"webm-fake-audio-bytes",
        )
    assert response.status_code == 200
    assert response.json()["status"] == "processing"
    # El TestClient ejecuta las background tasks tras la respuesta.
    mock_ingest.assert_called_once()
    assert mock_ingest.call_args.kwargs["title"] == "Reunión semanal"
    saved = mock_ingest.call_args.args[0]
    assert saved.exists()
    mock_reindex.assert_called_once()
    mock_summarize.assert_called_once_with(call.id)


def test_upload_processing_survives_reindex_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si la vectorización falla, el resumen se intenta igualmente (T-702)."""
    monkeypatch.setattr(settings, "enigma_data_path", tmp_path)
    call = _call("Daily")
    with (
        patch("enigma.api.ingest_audio", return_value=Mock(call=call)),
        patch("enigma.api.reindex_vault", side_effect=RuntimeError("Qdrant caído")),
        patch("enigma.api.summarize_call") as mock_summarize,
    ):
        response = client.post("/calls/upload", content=b"webm-fake-audio-bytes")
    assert response.status_code == 200
    mock_summarize.assert_called_once_with(call.id)


def test_upload_processing_aborts_when_ingest_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si la ingesta falla, no se vectoriza ni se resume (T-702)."""
    monkeypatch.setattr(settings, "enigma_data_path", tmp_path)
    with (
        patch("enigma.api.ingest_audio", side_effect=RuntimeError("audio corrupto")),
        patch("enigma.api.reindex_vault") as mock_reindex,
        patch("enigma.api.summarize_call") as mock_summarize,
    ):
        response = client.post("/calls/upload", content=b"webm-fake-audio-bytes")
    assert response.status_code == 200
    mock_reindex.assert_not_called()
    mock_summarize.assert_not_called()


def test_upload_call_rejects_empty_body(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enigma_data_path", tmp_path)
    response = client.post("/calls/upload", params={"title": "Vacía"}, content=b"")
    assert response.status_code == 422


# ── GET /calls/{id}/notes ────────────────────────────────────────────────────


def _note_summary(call_id: object, title: str) -> NoteSummary:
    return NoteSummary(
        path=Path(f"/vault/inbox/{uuid4().hex}.md"),
        note_id=uuid4(),
        title=title,
        created_at=datetime.now(tz=UTC),
        status="draft",
        tags=["equipo"],
        call_id=call_id,  # type: ignore[arg-type]
    )


def test_call_notes_returns_only_that_calls_notes() -> None:
    target = uuid4()
    other = uuid4()
    summaries = [
        _note_summary(target, "Nota de la llamada"),
        _note_summary(other, "Nota de otra llamada"),
    ]
    with patch("enigma.api.list_vault_notes", return_value=summaries):
        response = client.get(f"/calls/{target}/notes")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["title"] == "Nota de la llamada"


def test_call_notes_empty_when_no_match() -> None:
    with patch("enigma.api.list_vault_notes", return_value=[_note_summary(uuid4(), "X")]):
        response = client.get(f"/calls/{uuid4()}/notes")
    assert response.status_code == 200
    assert response.json() == []


# ── WebSocket /ws ────────────────────────────────────────────────────────────


def test_ws_hello_returns_welcome_presence_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "enigma_data_path", tmp_path)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "name": "Ana"})
        msgs = [ws.receive_json() for _ in range(3)]
    by_type = {m["type"]: m for m in msgs}
    assert set(by_type) == {"welcome", "presence", "history"}
    assert by_type["welcome"]["peer_id"]
    assert isinstance(by_type["welcome"]["ice_servers"], list)


def test_ws_call_signaling_relays_between_peers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "enigma_data_path", tmp_path)
    with client.websocket_connect("/ws") as a, client.websocket_connect("/ws") as b:
        a.send_json({"type": "hello", "name": "Ana"})
        a_msgs = [a.receive_json() for _ in range(3)]
        peer_a = next(m["peer_id"] for m in a_msgs if m["type"] == "welcome")

        b.send_json({"type": "hello", "name": "Beto"})
        b_msgs = [b.receive_json() for _ in range(3)]
        peer_b = next(m["peer_id"] for m in b_msgs if m["type"] == "welcome")

        a.send_json({"type": "call-join"})
        b.send_json({"type": "call-join"})
        a.send_json({"type": "signal", "to": peer_b, "data": {"sdp": "oferta"}})

        signal = None
        for _ in range(8):
            msg = b.receive_json()
            if msg["type"] == "signal":
                signal = msg
                break

    assert signal is not None
    assert signal["from"] == peer_a
    assert signal["data"] == {"sdp": "oferta"}


def test_ws_chat_is_broadcast(tmp_path: object, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "enigma_data_path", tmp_path)
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "hello", "name": "Ana"})
        for _ in range(3):  # welcome + presence + history
            ws.receive_json()
        ws.send_json({"type": "chat", "channel": "general", "body": "hola equipo"})
        chat = ws.receive_json()
    assert chat["type"] == "chat"
    assert chat["message"]["body"] == "hola equipo"
    assert chat["message"]["author"] == "Ana"
    assert chat["message"]["channel"] == "general"


# ── enigma serve ─────────────────────────────────────────────────────────────


def test_serve_invokes_uvicorn() -> None:
    with patch("uvicorn.run") as mock_run:
        result = runner.invoke(cli_app, ["serve", "--host", "127.0.0.1", "--port", "9001"])
    assert result.exit_code == 0
    kwargs = mock_run.call_args.kwargs
    assert mock_run.call_args.args[0] == "enigma.api:app"
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 9001
