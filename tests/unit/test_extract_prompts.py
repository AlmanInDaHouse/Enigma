"""Tests para `enigma.extract.prompts` (T-105)."""

from enigma.extract.prompts import (
    SYSTEM_PROMPT,
    USER_PROMPT_TEMPLATE,
    build_extraction_messages,
)


def test_system_prompt_declares_zettelkasten_role() -> None:
    assert "Zettelkasten" in SYSTEM_PROMPT
    assert "atómicas" in SYSTEM_PROMPT


def test_system_prompt_contains_all_six_core_rules() -> None:
    """Las 6 reglas críticas del prompt v1 deben estar presentes."""
    rules_keywords = [
        "una sola idea",  # 1: atomicidad
        "200 palabras",  # 2: longitud máxima del cuerpo
        "80 caracteres",  # 3: longitud máxima del título
        "relleno",  # 4: prohibido el filler conversacional
        "factual",  # 5: contenido factual; opinión marcada
        "JSON",  # 6: salida JSON válida
    ]
    for keyword in rules_keywords:
        assert keyword in SYSTEM_PROMPT, f"Falta keyword de regla: {keyword!r}"


def test_system_prompt_specifies_json_array_schema() -> None:
    """El formato de salida debe enumerar los 6 campos esperados por nota."""
    expected_keys = [
        '"title"',
        '"body"',
        '"tags"',
        '"timestamp_start"',
        '"timestamp_end"',
        '"speakers"',
    ]
    for key in expected_keys:
        assert key in SYSTEM_PROMPT, f"Falta campo {key} en el schema JSON"


def test_system_prompt_handles_empty_chunk_case() -> None:
    """Si no hay ideas en el chunk, el modelo debe devolver `[]`."""
    assert "[]" in SYSTEM_PROMPT


def test_user_template_has_placeholders() -> None:
    assert "{transcript_chunk}" in USER_PROMPT_TEMPLATE
    assert "{language}" in USER_PROMPT_TEMPLATE


def test_build_messages_default_language_is_spanish() -> None:
    msgs = build_extraction_messages("hola mundo")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert msgs[1]["role"] == "user"
    assert "Idioma de la transcripción: es" in msgs[1]["content"]
    assert "hola mundo" in msgs[1]["content"]


def test_build_messages_accepts_explicit_language() -> None:
    msgs = build_extraction_messages("hello world", language="en")
    assert "Idioma de la transcripción: en" in msgs[1]["content"]
    assert "hello world" in msgs[1]["content"]


def test_build_messages_passes_special_chars_literally() -> None:
    """Llaves, comillas y saltos de línea en el chunk no rompen el render."""
    chunk = "Manuel: { 'precio': 100 }\nCliente: '¿y el {descuento}?'"
    msgs = build_extraction_messages(chunk)
    assert chunk in msgs[1]["content"]


def test_build_messages_system_prompt_is_invariant() -> None:
    """El system prompt no depende del chunk; es constante entre llamadas."""
    a = build_extraction_messages("alpha")[0]["content"]
    b = build_extraction_messages("beta", language="en")[0]["content"]
    assert a == b == SYSTEM_PROMPT
