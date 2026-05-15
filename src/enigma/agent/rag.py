"""Pipeline RAG: pregunta → retrieve → LLM → respuesta con citas (T-302).

Implementación "a mano" sobre los componentes que Enigma ya controla
(`search_notes` de T-301 + Ollama), sin LlamaIndex. Decisión registrada en
`PLAN.md`: LlamaIndex envolvería piezas ya resueltas y CONSTITUTION §6 exige
justificar cada dependencia — no aporta lo suficiente para 6 personas.

Flujo de `answer_question`:
1. Recupera las `top_k` notas más cercanas con `search_notes`.
2. Carga sus cuerpos del Vault (`load_notes_by_ids`) — el payload Qdrant no
   los trae. Solo entran al contexto las notas que existen en disco.
3. Si no hay contexto, devuelve una respuesta determinista sin llamar al LLM.
4. Genera la respuesta con el LLM local sobre el contexto.
5. Parsea los `[[wikilink]]` de la respuesta y los casa contra los stems de
   las notas de contexto: una cita solo cuenta si apunta a una nota
   recuperada — así se garantiza que el fichero citado existe.
"""

import logging
import re
from functools import lru_cache
from pathlib import Path
from uuid import UUID

import ollama
from pydantic import BaseModel, ConfigDict

from enigma.agent.prompts import build_rag_messages
from enigma.config import settings
from enigma.models.note import Note
from enigma.search import SearchResult, search_notes
from enigma.vault.reader import load_notes_by_ids
from enigma.vault.writer import note_stem

_log = logging.getLogger(__name__)

_WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
"""Captura el interior de un `[[wikilink]]` (stem o `stem|título`)."""

NO_CONTEXT_ANSWER = "No encontré información en el Vault para responder a esa pregunta."
"""Respuesta determinista cuando el retrieval no devuelve notas utilizables."""


class RagError(RuntimeError):
    """El LLM falló al generar la respuesta RAG."""


class Citation(BaseModel):
    """Una nota del contexto efectivamente citada en la respuesta."""

    model_config = ConfigDict(extra="forbid")

    note_id: UUID
    title: str
    stem: str


class RagAnswer(BaseModel):
    """Respuesta RAG: texto, citas verificadas y notas recuperadas."""

    model_config = ConfigDict(extra="forbid")

    question: str
    answer: str
    citations: list[Citation]
    sources: list[SearchResult]


@lru_cache(maxsize=1)
def _client() -> ollama.Client:
    """Cliente Ollama cacheado, apuntando a `settings.ollama_host`."""
    return ollama.Client(host=settings.ollama_host)


def _llm_answer(messages: list[dict[str, str]], *, model: str) -> str:
    """Genera la respuesta en texto libre con el LLM local.

    Raises:
        RagError: si el LLM no devuelve una respuesta utilizable.
    """
    try:
        response = _client().chat(
            model=model,
            messages=messages,
            options={"temperature": 0.2},
        )
        return str(response["message"]["content"]).strip()
    except (ollama.ResponseError, KeyError) as exc:
        raise RagError(f"El LLM falló al generar la respuesta: {exc}") from exc


def _extract_citations(answer: str, context_notes: list[Note]) -> list[Citation]:
    """Parsea los `[[wikilink]]` de `answer` y los casa con el contexto.

    Solo se cuentan citas cuyo stem corresponda a una nota del contexto (que
    por construcción existe en disco). Un wikilink alucinado por el LLM que no
    case con ninguna nota recuperada se ignora. Sin duplicados.
    """
    stem_to_note = {note_stem(n.id, n.title): n for n in context_notes}
    citations: list[Citation] = []
    seen: set[UUID] = set()
    for raw in _WIKILINK_RE.findall(answer):
        stem = raw.split("|", 1)[0].strip()
        note = stem_to_note.get(stem)
        if note is None or note.id in seen:
            continue
        seen.add(note.id)
        citations.append(Citation(note_id=note.id, title=note.title, stem=stem))
    return citations


def answer_question(
    question: str,
    *,
    top_k: int = 5,
    model: str | None = None,
    vault_path: Path | None = None,
) -> RagAnswer:
    """Responde `question` con RAG sobre el Vault y devuelve la respuesta + citas.

    Args:
        question: Pregunta en lenguaje natural.
        top_k: Número de notas a recuperar como contexto.
        model: Override del LLM. Default `settings.ollama_llm_model`.
        vault_path: Raíz del Vault. Default `settings.enigma_vault_path`.

    Returns:
        `RagAnswer` con el texto, las citas verificadas y las notas recuperadas.

    Raises:
        RagError: si el LLM falla al generar la respuesta.
    """
    sources = search_notes(question, top_k=top_k)
    notes_by_id = load_notes_by_ids({s.note_id for s in sources}, vault_path)

    # Notas de contexto en el orden de relevancia del retrieval; solo las que
    # existen en disco (un punto Qdrant huérfano no rompe el RAG).
    context_notes = [notes_by_id[s.note_id] for s in sources if s.note_id in notes_by_id]
    if not context_notes:
        _log.info("RAG sin contexto utilizable para la pregunta")
        return RagAnswer(
            question=question,
            answer=NO_CONTEXT_ANSWER,
            citations=[],
            sources=sources,
        )

    messages = build_rag_messages(question, context_notes)
    answer = _llm_answer(messages, model=model or settings.ollama_llm_model)
    citations = _extract_citations(answer, context_notes)

    return RagAnswer(
        question=question,
        answer=answer,
        citations=citations,
        sources=sources,
    )
