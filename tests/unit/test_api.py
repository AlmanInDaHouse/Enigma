"""Tests para la API REST de Enigma (T-305).

Usan `TestClient` de FastAPI y mockean `answer_question` para verificar el
contrato del endpoint sin tocar el pipeline RAG real.
"""

from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from enigma.agent.rag import Citation, RagAnswer, RagError
from enigma.api import app
from enigma.cli import app as cli_app
from enigma.search import SearchResult

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


# ── enigma serve ─────────────────────────────────────────────────────────────


def test_serve_invokes_uvicorn() -> None:
    with patch("uvicorn.run") as mock_run:
        result = runner.invoke(cli_app, ["serve", "--host", "127.0.0.1", "--port", "9001"])
    assert result.exit_code == 0
    kwargs = mock_run.call_args.kwargs
    assert mock_run.call_args.args[0] == "enigma.api:app"
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 9001
