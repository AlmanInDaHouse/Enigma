"""API REST interna de Enigma (T-305, RF-14).

Expone el pipeline RAG (T-302) como un endpoint HTTP para que clientes
distintos de la CLI (p.ej. un plugin de Obsidian o un script) puedan
consultar el Vault:

- `GET  /health` → sanity-check, sin tocar el LLM ni Qdrant.
- `POST /ask`    → pregunta en lenguaje natural → respuesta RAG con citas.

La app se sirve con `enigma serve` (uvicorn). `RagAnswer` ya es un modelo
Pydantic, así que FastAPI serializa la respuesta — incluidas `citations` y
`sources` — a JSON sin trabajo extra.
"""

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator

from enigma import __version__
from enigma.agent.rag import RagAnswer, RagError, answer_question

app = FastAPI(
    title="Enigma API",
    version=__version__,
    description="Segundo cerebro conversacional local-first — endpoint RAG.",
)


class AskRequest(BaseModel):
    """Cuerpo de una petición `POST /ask`."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(..., min_length=1, description="Pregunta en lenguaje natural.")
    top_k: int = Field(5, ge=1, description="Número de notas a usar como contexto.")
    rerank: bool | None = Field(
        None,
        description="Fuerza on/off el reranking. None usa la config del servidor.",
    )

    @field_validator("question")
    @classmethod
    def _question_not_blank(cls, value: str) -> str:
        """Rechaza preguntas en blanco (solo espacios)."""
        if not value.strip():
            raise ValueError("La pregunta no puede estar vacía.")
        return value


@app.get("/health")
def health() -> dict[str, str]:
    """Sanity-check del servicio. No consulta el LLM ni Qdrant."""
    return {"status": "ok", "version": __version__}


@app.post("/ask", response_model=RagAnswer)
def ask(request: AskRequest) -> RagAnswer:
    """Responde una pregunta con RAG sobre el Vault y devuelve citas verificadas.

    Raises:
        HTTPException: 503 si el LLM local falla al generar la respuesta.
    """
    try:
        return answer_question(
            request.question,
            top_k=request.top_k,
            rerank=request.rerank,
        )
    except RagError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
