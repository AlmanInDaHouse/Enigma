"""API REST interna de Enigma (T-305, RF-14) + interfaz web.

Expone el pipeline de Enigma por HTTP y sirve una interfaz web sobre la misma
app (`src/enigma/web/`), para que el equipo pueda usar Enigma desde el
navegador además de la CLI:

- `GET  /`         → interfaz web (single-page).
- `GET  /health`   → sanity-check, sin tocar el LLM ni Qdrant.
- `GET  /stats`    → métricas del sistema (corpus, actividad, salud).
- `GET  /search`   → búsqueda semántica top-k de notas.
- `GET  /channels` → canales de chat disponibles.
- `POST /ask`      → pregunta en lenguaje natural → respuesta RAG con citas.
- `WS   /ws`       → chat en vivo + presencia del equipo (Fase 6 — W1).

La app se sirve con `enigma serve` (uvicorn). Los modelos de respuesta ya son
Pydantic, así que FastAPI los serializa a JSON sin trabajo extra.
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from enigma import __version__
from enigma.agent.rag import RagAnswer, RagError, answer_question
from enigma.config import settings
from enigma.realtime import CHANNELS, manager, recent_messages, store_chat
from enigma.search import SearchResult, search_notes
from enigma.stats import EnigmaStats, gather_stats

_WEB_DIR = Path(__file__).parent / "web"

app = FastAPI(
    title="Enigma API",
    version=__version__,
    description="Segundo cerebro conversacional local-first — RAG + interfaz web.",
)

# Activos estáticos de la interfaz web (CSS, JS).
app.mount("/static", StaticFiles(directory=_WEB_DIR), name="static")


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


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """Sirve la interfaz web de Enigma."""
    return FileResponse(_WEB_DIR / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    """Sanity-check del servicio. No consulta el LLM ni Qdrant."""
    return {"status": "ok", "version": __version__}


@app.get("/stats", response_model=EnigmaStats)
def stats() -> EnigmaStats:
    """Métricas del sistema: corpus, actividad y sondeo de salud en vivo."""
    return gather_stats()


@app.get("/search", response_model=list[SearchResult])
def search(
    q: str = Query(..., min_length=1, description="Consulta en lenguaje natural."),
    top_k: int = Query(5, ge=1, le=50, description="Número de notas a recuperar."),
) -> list[SearchResult]:
    """Búsqueda semántica de notas en el Vault.

    Una consulta en blanco se rechaza con 422.
    """
    if not q.strip():
        raise HTTPException(status_code=422, detail="La consulta no puede estar vacía.")
    return search_notes(q, top_k=top_k)


@app.get("/channels", response_model=list[str])
def channels() -> list[str]:
    """Canales de chat disponibles para el equipo."""
    return list(CHANNELS)


async def _handle_hello(websocket: WebSocket, data: dict[str, object]) -> tuple[str, str]:
    """Procesa `hello`: registra al cliente y le envía welcome + historial."""
    name = (str(data.get("name") or "").strip()[:60]) or "anónimo"
    peer_id = await manager.register(websocket, name)
    await websocket.send_json(
        {"type": "welcome", "peer_id": peer_id, "ice_servers": settings.webrtc_ice_servers},
    )
    history = [m.model_dump(mode="json") for m in recent_messages()]
    await websocket.send_json({"type": "history", "messages": history})
    return name, peer_id


async def _handle_chat(name: str, data: dict[str, object]) -> None:
    """Procesa `chat`: persiste el mensaje y lo difunde."""
    message = store_chat(name, str(data.get("channel", "")), str(data.get("body", "")))
    if message is not None:
        await manager.broadcast(
            {"type": "chat", "message": message.model_dump(mode="json")},
        )


@app.websocket("/ws")
async def chat_socket(websocket: WebSocket) -> None:
    """Canal en vivo del equipo: chat, presencia y señalización WebRTC (Fase 6).

    Protocolo (JSON por mensaje):
    - cliente → `hello` se presenta · `chat` envía mensaje.
    - cliente → `call-join` / `call-leave` entra/sale de la llamada.
    - cliente → `signal` `{to, data}` relaya señalización WebRTC a un par.
    - servidor → `welcome` `{peer_id, ice_servers}` · `presence` · `history`
      · `chat` · `call-roster` · `call-joined` · `call-left` · `signal`.
    """
    await websocket.accept()
    name: str | None = None
    peer_id: str | None = None
    try:
        while True:
            data = await websocket.receive_json()
            kind = data.get("type")
            if kind == "hello":
                name, peer_id = await _handle_hello(websocket, data)
            elif kind == "chat" and name is not None:
                await _handle_chat(name, data)
            elif kind == "call-join" and peer_id is not None:
                await manager.join_call(websocket)
            elif kind == "call-leave" and peer_id is not None:
                await manager.leave_call(websocket)
            elif kind == "signal" and peer_id is not None:
                await manager.relay_signal(websocket, str(data.get("to", "")), data.get("data"))
    except WebSocketDisconnect:
        pass
    finally:
        await manager.unregister(websocket)


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
