"""API REST interna de Enigma (T-305, RF-14) + interfaz web.

Expone el pipeline de Enigma por HTTP y sirve una interfaz web sobre la misma
app (`src/enigma/web/`), para que el equipo pueda usar Enigma desde el
navegador además de la CLI:

- `GET  /`         → interfaz web (single-page).
- `GET  /health`   → sanity-check, sin tocar el LLM ni Qdrant.
- `GET  /stats`    → métricas del sistema (corpus, actividad, salud).
- `GET  /search`   → búsqueda semántica top-k de notas.
- `GET  /channels` → canales de chat disponibles.
- `GET  /calls`    → llamadas registradas y su estado de procesado.
- `GET  /calls/{id}/notes` → notas extraídas de una llamada.
- `POST /ask`      → pregunta en lenguaje natural → respuesta RAG con citas.
- `POST /calls/upload` → sube la grabación de una llamada → pipeline.
- `WS   /ws`       → chat + presencia + señalización WebRTC (Fase 6).

La app se sirve con `enigma serve` (uvicorn). Los modelos de respuesta ya son
Pydantic, así que FastAPI los serializa a JSON sin trabajo extra.
"""

import logging
from datetime import datetime
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import (
    BackgroundTasks,
    FastAPI,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from enigma import __version__
from enigma.agent.decisions import extract_decisions_from_call
from enigma.agent.rag import RagAnswer, RagError, answer_question
from enigma.agent.summarizer import CallSummary, read_call_summary, summarize_call
from enigma.agent.tasks_extractor import extract_tasks_from_call
from enigma.config import settings
from enigma.db import calls as calls_db
from enigma.db.sqlite import get_connection
from enigma.ingest.transcriber import load_transcript
from enigma.pipeline import ingest_audio
from enigma.realtime import CHANNELS, manager, recent_messages, store_chat
from enigma.search import SearchResult, search_notes
from enigma.stats import EnigmaStats, gather_stats
from enigma.vault.reader import list_vault_notes
from enigma.vector.qdrant_client import VectorStoreUnavailableError
from enigma.vector.reindexer import reindex_vault

_log = logging.getLogger(__name__)
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
    try:
        return search_notes(q, top_k=top_k)
    except VectorStoreUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/channels", response_model=list[str])
def channels() -> list[str]:
    """Canales de chat disponibles para el equipo."""
    return list(CHANNELS)


class CallCard(BaseModel):
    """Vista ligera de una llamada para el listado de la app."""

    model_config = ConfigDict(extra="forbid")

    id: UUID
    title: str | None
    status: str
    recorded_at: datetime
    duration_seconds: float


@app.get("/calls", response_model=list[CallCard])
def calls() -> list[CallCard]:
    """Últimas llamadas registradas y su estado de procesado."""
    with get_connection() as conn:
        rows = calls_db.list_calls(conn, limit=20)
    return [
        CallCard(
            id=call.id,
            title=call.title,
            status=call.status,
            recorded_at=call.recorded_at,
            duration_seconds=call.duration_seconds,
        )
        for call in rows
    ]


class CallNote(BaseModel):
    """Una nota atómica extraída de una llamada."""

    model_config = ConfigDict(extra="forbid")

    note_id: UUID
    title: str
    status: str
    tags: list[str]


@app.get("/calls/{call_id}/notes", response_model=list[CallNote])
def call_notes(call_id: UUID) -> list[CallNote]:
    """Notas del Vault extraídas de una llamada concreta."""
    return [
        CallNote(
            note_id=summary.note_id,
            title=summary.title,
            status=summary.status,
            tags=summary.tags,
        )
        for summary in list_vault_notes()
        if summary.call_id == call_id
    ]


class CallTask(BaseModel):
    """Una tarea pendiente mencionada en una llamada."""

    model_config = ConfigDict(extra="forbid")

    statement: str
    assignee: str | None


class CallDetail(BaseModel):
    """Vista de detalle de una llamada grabada: lo que la IA destiló de ella."""

    model_config = ConfigDict(extra="forbid")

    call_id: UUID
    title: str | None
    status: str
    summary: CallSummary | None
    notes: list[CallNote]
    decisions: list[str]
    tasks: list[CallTask]


@app.get("/calls/{call_id}/detail", response_model=CallDetail)
def call_detail(call_id: UUID) -> CallDetail:
    """Detalle de una llamada grabada: resumen IA + notas + decisiones + tareas.

    El resumen se lee de la nota que generó la ingesta (`null` si aún no
    existe). Las decisiones y las tareas se extraen on-demand del transcript
    — son dos llamadas al LLM local, así que la respuesta puede tardar
    ~10-30 s. Un fallo de extracción degrada a lista vacía: la vista nunca se
    rompe por ello.

    Raises:
        HTTPException: 404 si la llamada no existe.
    """
    with get_connection() as conn:
        call = calls_db.get_call(conn, call_id)
    if call is None:
        raise HTTPException(status_code=404, detail="No existe esa llamada.")

    notes = [
        CallNote(
            note_id=summary.note_id,
            title=summary.title,
            status=summary.status,
            tags=summary.tags,
        )
        for summary in list_vault_notes()
        if summary.call_id == call_id
    ]
    summary = read_call_summary(call)

    decisions: list[str] = []
    tasks: list[CallTask] = []
    transcript = load_transcript(call_id)
    if transcript is not None:
        try:
            decisions = [d.statement for d in extract_decisions_from_call(call, transcript)]
        except Exception:
            _log.exception("Falló la extracción de decisiones de la llamada %s", call_id)
        try:
            tasks = [
                CallTask(statement=t.statement, assignee=t.assignee)
                for t in extract_tasks_from_call(call, transcript)
            ]
        except Exception:
            _log.exception("Falló la extracción de tareas de la llamada %s", call_id)

    return CallDetail(
        call_id=call_id,
        title=call.title,
        status=call.status,
        summary=summary,
        notes=notes,
        decisions=decisions,
        tasks=tasks,
    )


def _process_upload(audio_path: Path, title: str) -> None:
    """Job en background: mete la grabación en el pipeline y la deja consultable.

    Encadena las tres etapas que cierran el bucle "grabar → IA → consultar":

        1. `ingest_audio` — transcribe y extrae notas atómicas al Vault.
        2. `reindex_vault` — vectoriza las notas en Qdrant (las hace
           consultables por RAG y `/ask`).
        3. `summarize_call` — genera el resumen IA en `vault/calls/`.

    `ingest` es la etapa crítica: si falla, no hay nada que enriquecer. La
    vectorización y el resumen son enriquecimiento independiente — cada uno se
    aísla en su `try/except` para que un fallo (p.ej. Qdrant caído) no impida
    el otro. Las notas ya quedan en el Vault, fuente de verdad, pase lo que
    pase; un reindex fallido se recupera luego con `enigma reindex`.
    """
    try:
        result = ingest_audio(audio_path, title=title)
    except Exception:
        _log.exception("Falló la ingesta de la grabación %s", audio_path)
        return
    call_id = result.call.id
    try:
        reindex_vault()
    except Exception:
        _log.exception("Falló la vectorización tras subir la llamada %s", call_id)
    try:
        summarize_call(call_id)
    except Exception:
        _log.exception("Falló el resumen de la llamada %s", call_id)


@app.post("/calls/upload")
async def upload_call(
    request: Request,
    background: BackgroundTasks,
    title: str = Query("Llamada del equipo", description="Título de la llamada."),
) -> dict[str, str]:
    """Recibe la grabación de una llamada y la procesa en segundo plano.

    El cuerpo de la petición es el audio crudo (p.ej. `audio/webm`). La
    ingesta (transcripción + extracción) es lenta, así que se lanza como job
    en background y la respuesta vuelve de inmediato.
    """
    audio = await request.body()
    if not audio:
        raise HTTPException(status_code=422, detail="La grabación está vacía.")
    uploads = settings.enigma_data_path / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    audio_path = uploads / f"{uuid4().hex}.webm"
    audio_path.write_bytes(audio)
    background.add_task(_process_upload, audio_path, title)
    return {"status": "processing", "title": title}


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

    Un servicio caído (Qdrant o el LLM) o cualquier fallo inesperado devuelve
    un 503 con un mensaje accionable — nunca un 500 opaco que el frontend solo
    pueda mostrar como "Error 500".

    Raises:
        HTTPException: 503 si la base vectorial o el LLM local no responden.
    """
    try:
        return answer_question(
            request.question,
            top_k=request.top_k,
            rerank=request.rerank,
        )
    except (VectorStoreUnavailableError, RagError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # red de seguridad: nunca un 500 opaco
        _log.exception("Fallo inesperado al responder /ask")
        raise HTTPException(
            status_code=503,
            detail=(
                "Enigma no pudo responder ahora mismo. Comprueba que Qdrant y "
                "Ollama estén arrancados."
            ),
        ) from exc
