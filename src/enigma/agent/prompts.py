"""Plantillas de prompt para los agentes RAG y analítico.

- `build_rag_messages()` (T-302): pregunta + contexto → respuesta con citas.
- `build_summary_messages()` (T-401): transcript → resumen ejecutivo en JSON.

Cada bloque de contexto del RAG incluye el wikilink `[[stem|título]]` literal
que el modelo debe usar para citar esa nota — así la cita resuelve a un
fichero real del Vault (el `stem` es el nombre del fichero sin `.md`, ver
`vault/writer.py`).
"""

from enigma.models.note import Note
from enigma.vault.writer import note_stem

SYSTEM_PROMPT = """\
Eres el asistente de consulta de Enigma, un segundo cerebro basado en notas
atómicas estilo Zettelkasten.

REGLAS:
1. Responde ÚNICAMENTE con la información de las NOTAS DE CONTEXTO. No uses
   conocimiento externo ni inventes datos.
2. Cita cada afirmación con el wikilink EXACTO que acompaña a cada nota, tal
   cual aparece (formato `[[stem|título]]`). No modifiques el stem.
3. Si las notas de contexto no contienen información suficiente para
   responder, dilo explícitamente y no inventes una respuesta.
4. Responde en español, de forma concisa y directa.
"""


_CONTEXT_NOTE_TEMPLATE = """\
NOTA {index} — cita como: {wikilink}
Título: {title}
Contenido: {body}
"""

USER_PROMPT_TEMPLATE = """\
PREGUNTA:
{question}

NOTAS DE CONTEXTO:
{context}
"""


def _format_context_note(index: int, note: Note) -> str:
    """Renderiza una nota como bloque de contexto numerado con su wikilink."""
    stem = note_stem(note.id, note.title)
    wikilink = f"[[{stem}|{note.title}]]"
    return _CONTEXT_NOTE_TEMPLATE.format(
        index=index,
        wikilink=wikilink,
        title=note.title,
        body=note.body,
    )


def build_rag_messages(question: str, notes: list[Note]) -> list[dict[str, str]]:
    """Construye los `messages` para Ollama chat con `system` + `user`.

    Args:
        question: Pregunta del usuario en lenguaje natural.
        notes: Notas recuperadas que sirven de contexto. Pueden ir vacías
            (el caller decide qué hacer en ese caso).

    Returns:
        Lista de dos dicts: `{"role": "system", ...}` y `{"role": "user", ...}`.
    """
    context = "\n".join(_format_context_note(i, note) for i, note in enumerate(notes, start=1))
    user_content = USER_PROMPT_TEMPLATE.format(question=question, context=context)
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


# ── Resumen ejecutivo de una llamada (T-401) ────────────────────────────────

SUMMARY_SYSTEM_PROMPT = """\
Eres un asistente que produce el resumen ejecutivo de una llamada de equipo.

Devuelve EXCLUSIVAMENTE un objeto JSON con esta forma exacta:
{
  "tldr": "...",
  "key_points": ["...", "..."],
  "topics": ["...", "..."]
}

REGLAS:
1. `tldr`: 2-3 frases que capturan la esencia de la llamada.
2. `key_points`: lista de los puntos concretos más relevantes (decisiones,
   acuerdos, datos, problemas). Entre 3 y 8 elementos.
3. `topics`: lista corta de los temas tratados, en 1-3 palabras cada uno.
4. Contenido factual, en español. NO incluyas relleno conversacional.
5. Si la transcripción es demasiado pobre para resumir, devuelve listas
   vacías y un `tldr` que lo indique.
"""


SUMMARY_USER_TEMPLATE = """\
Título de la llamada: {call_title}
Idioma: {language}

TRANSCRIPCIÓN:
{transcript_text}
"""


def build_summary_messages(
    transcript_text: str,
    *,
    call_title: str,
    language: str = "es",
) -> list[dict[str, str]]:
    """Construye los `messages` para resumir una llamada (Ollama chat, JSON).

    Args:
        transcript_text: Transcripción completa de la llamada, ya unida.
        call_title: Título de la llamada (o un texto de relleno si no tiene).
        language: Código ISO-639-1 del idioma de la llamada.

    Returns:
        Lista de dos dicts: `{"role": "system", ...}` y `{"role": "user", ...}`.
    """
    user_content = SUMMARY_USER_TEMPLATE.format(
        call_title=call_title,
        language=language,
        transcript_text=transcript_text,
    )
    return [
        {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


# ── Extracción de decisiones de una llamada (T-402) ─────────────────────────

DECISIONS_SYSTEM_PROMPT = """\
Eres un asistente que extrae las DECISIONES tomadas en una llamada de equipo.

Devuelve EXCLUSIVAMENTE un objeto JSON con esta forma exacta:
{
  "decisions": ["...", "..."]
}

REGLAS:
1. Una decisión es un acuerdo o resolución concreta que el equipo ADOPTA
   ("decidimos", "vamos a", "queda aprobado", "acordamos").
2. NO incluyas opiniones, ideas sueltas, dudas ni temas debatidos sin
   conclusión. Solo lo que se decide.
3. Cada decisión: una frase concisa y autocontenida, en español.
4. Si en la llamada no se tomó ninguna decisión, devuelve `{"decisions": []}`.
"""


DECISIONS_USER_TEMPLATE = """\
Título de la llamada: {call_title}
Idioma: {language}

TRANSCRIPCIÓN:
{transcript_text}
"""


def build_decisions_messages(
    transcript_text: str,
    *,
    call_title: str,
    language: str = "es",
) -> list[dict[str, str]]:
    """Construye los `messages` para extraer decisiones (Ollama chat, JSON).

    Args:
        transcript_text: Transcripción completa de la llamada, ya unida.
        call_title: Título de la llamada (o un texto de relleno si no tiene).
        language: Código ISO-639-1 del idioma de la llamada.

    Returns:
        Lista de dos dicts: `{"role": "system", ...}` y `{"role": "user", ...}`.
    """
    user_content = DECISIONS_USER_TEMPLATE.format(
        call_title=call_title,
        language=language,
        transcript_text=transcript_text,
    )
    return [
        {"role": "system", "content": DECISIONS_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


# ── Extracción de tareas pendientes de una llamada (T-403) ──────────────────

TASKS_SYSTEM_PROMPT = """\
Eres un asistente que extrae las TAREAS PENDIENTES mencionadas en una llamada
de equipo (acciones por hacer, compromisos, "to-dos").

Devuelve EXCLUSIVAMENTE un objeto JSON con esta forma exacta:
{
  "tasks": [
    {"statement": "...", "assignee": "..."},
    {"statement": "...", "assignee": null}
  ]
}

REGLAS:
1. Una tarea es una acción concreta pendiente de ejecutar ("hay que...",
   "me encargo de...", "queda pendiente...", "tenemos que...").
2. `statement`: la acción, en una frase concisa y autocontenida, en español.
3. `assignee`: el nombre de la persona responsable si se identifica en la
   llamada; usa `null` si no se menciona ningún responsable claro.
4. NO incluyas decisiones ya cerradas, opiniones ni temas debatidos.
5. Si no hay ninguna tarea pendiente, devuelve `{"tasks": []}`.
"""


TASKS_USER_TEMPLATE = """\
Título de la llamada: {call_title}
Idioma: {language}

TRANSCRIPCIÓN:
{transcript_text}
"""


def build_tasks_messages(
    transcript_text: str,
    *,
    call_title: str,
    language: str = "es",
) -> list[dict[str, str]]:
    """Construye los `messages` para extraer tareas pendientes (Ollama chat, JSON).

    Args:
        transcript_text: Transcripción completa de la llamada, ya unida.
        call_title: Título de la llamada (o un texto de relleno si no tiene).
        language: Código ISO-639-1 del idioma de la llamada.

    Returns:
        Lista de dos dicts: `{"role": "system", ...}` y `{"role": "user", ...}`.
    """
    user_content = TASKS_USER_TEMPLATE.format(
        call_title=call_title,
        language=language,
        transcript_text=transcript_text,
    )
    return [
        {"role": "system", "content": TASKS_SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
