"""Plantillas de prompt para el extractor LLM (T-105).

Define el `SYSTEM_PROMPT` con las 6 reglas de extracción atómica (alineado
con `spec.md §Prompt de extracción v1`) y el `USER_PROMPT_TEMPLATE` con los
placeholders `{language}` y `{transcript_chunk}`.

`build_extraction_messages()` arma la estructura `messages=[{role, content}]`
que espera el cliente Ollama (`/api/chat`). El cliente real vive en T-107.

El `USER_PROMPT_TEMPLATE` es la única cadena que pasa por `str.format`; el
`SYSTEM_PROMPT` contiene llaves literales del JSON de ejemplo y NUNCA se
formatea para no romper en esas llaves.
"""

SYSTEM_PROMPT = """\
Eres un asistente que convierte transcripciones de llamadas en notas atómicas estilo Zettelkasten.

REGLAS:
1. Una nota = una sola idea.
2. Cuerpo de 1-3 párrafos, máximo 200 palabras.
3. Título conciso, descriptivo, < 80 caracteres.
4. NO incluyas relleno conversacional ("creo que", "pues entonces").
5. Mantén el contenido factual; si es opinión, indícalo.
6. Devuelve EXCLUSIVAMENTE un array JSON. NO envuelvas el array en un objeto.
   La salida debe empezar con `[` y terminar con `]`.

FORMATO de salida obligatorio (JSON):
[
  {
    "title": "...",
    "body": "...",
    "tags": ["tag1", "tag2"],
    "timestamp_start": 412.5,
    "timestamp_end": 478.2,
    "speakers": ["SPEAKER_00"]
  }
]

Si el chunk no contiene ideas extraíbles, devuelve `[]`.

NO devuelvas un objeto del tipo `{"notes": [...]}` ni `{"result": [...]}`.
Devuelve directamente el array.
"""


USER_PROMPT_TEMPLATE = """\
Idioma de la transcripción: {language}

TRANSCRIPCIÓN:
{transcript_chunk}
"""


def build_extraction_messages(
    transcript_chunk: str,
    *,
    language: str = "es",
) -> list[dict[str, str]]:
    """Construye los `messages` para Ollama chat con `system` + `user`.

    Args:
        transcript_chunk: Bloque de transcripción a procesar (puede contener
            llaves, saltos de línea, comillas — se pasa literal al user).
        language: Código ISO-639-1 del idioma (default `es`). Se inyecta en
            el user prompt para ayudar al modelo a producir tags y títulos
            consistentes con el idioma fuente.

    Returns:
        Lista de dos dicts: `{"role": "system", "content": ...}` y
        `{"role": "user", "content": ...}`.
    """
    user_content = USER_PROMPT_TEMPLATE.format(
        language=language,
        transcript_chunk=transcript_chunk,
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
