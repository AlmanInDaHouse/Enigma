"""Tests para el comando `enigma ask` (T-303).

Mockean `answer_question` para verificar el render y el manejo de errores de
la CLI sin tocar el pipeline RAG real.
"""

from datetime import UTC, datetime
from unittest.mock import patch
from uuid import uuid4

from typer.testing import CliRunner

from enigma.agent.rag import Citation, RagAnswer, RagError
from enigma.cli import app
from enigma.search import SearchResult

runner = CliRunner()


def _source(title: str = "Estrategia padel") -> SearchResult:
    return SearchResult(
        note_id=uuid4(),
        title=title,
        score=0.9,
        tags=["t"],
        status="draft",
        call_id=uuid4(),
        created_at=datetime.now(tz=UTC),
    )


def _answer(answer: str = "Captamos socios por densidad.", *, cited: bool = True) -> RagAnswer:
    citations = (
        [Citation(note_id=uuid4(), title="Estrategia padel", stem="estrategia-padel-abc12345")]
        if cited
        else []
    )
    return RagAnswer(
        question="¿Cómo captamos socios?",
        answer=answer,
        citations=citations,
        sources=[_source()],
    )


def test_ask_shows_answer() -> None:
    with patch("enigma.agent.rag.answer_question", return_value=_answer("Respuesta clara.")):
        result = runner.invoke(app, ["ask", "¿Cómo captamos socios?"])
    assert result.exit_code == 0
    assert "Respuesta clara." in result.output


def test_ask_shows_citations() -> None:
    with patch("enigma.agent.rag.answer_question", return_value=_answer()):
        result = runner.invoke(app, ["ask", "¿Cómo captamos socios?"])
    assert result.exit_code == 0
    assert "estrategia-padel-abc12345" in result.output
    assert "Estrategia padel" in result.output


def test_ask_warns_when_no_citations() -> None:
    with patch("enigma.agent.rag.answer_question", return_value=_answer(cited=False)):
        result = runner.invoke(app, ["ask", "pregunta sin contexto"])
    assert result.exit_code == 0
    assert "no cita ninguna nota" in result.output


def test_ask_rejects_blank_question() -> None:
    result = runner.invoke(app, ["ask", "   "])
    assert result.exit_code != 0


def test_ask_handles_rag_error() -> None:
    with patch("enigma.agent.rag.answer_question", side_effect=RagError("LLM caído")):
        result = runner.invoke(app, ["ask", "pregunta"])
    assert result.exit_code == 1
    assert "Error" in result.output


def test_ask_propagates_top_k() -> None:
    with patch("enigma.agent.rag.answer_question", return_value=_answer()) as mock_answer:
        result = runner.invoke(app, ["ask", "pregunta", "--top-k", "9"])
    assert result.exit_code == 0
    assert mock_answer.call_args.kwargs["top_k"] == 9
