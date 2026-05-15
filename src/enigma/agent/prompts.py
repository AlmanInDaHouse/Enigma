"""Plantillas de prompt para el pipeline RAG (T-302).

`build_rag_messages()` arma los `messages` para Ollama chat: un `SYSTEM_PROMPT`
con las reglas de respuesta (responder solo con el contexto, citar con
wikilinks) y un `user` con la pregunta más los bloques de contexto.

Cada bloque de contexto incluye el wikilink `[[stem|título]]` literal que el
modelo debe usar para citar esa nota — así la cita resuelve a un fichero real
del Vault (el `stem` es el nombre del fichero sin `.md`, ver `vault/writer.py`).
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
