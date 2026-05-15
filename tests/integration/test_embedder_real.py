"""Integration test: embedder real contra Ollama + nomic-embed-text (T-202).

Marcado `@pytest.mark.integration`, excluido del CI. Para correrlo local:

    uv run pytest -m integration tests/integration/test_embedder_real.py

Requiere Ollama corriendo con `nomic-embed-text` disponible (`ollama list`).
"""

import time

import pytest

from enigma.vector.embedder import EMBEDDING_DIM, embed_text


@pytest.mark.integration
def test_embed_text_real_returns_768_float_vector() -> None:
    vector = embed_text("una frase de prueba en español sobre estrategia")
    assert len(vector) == EMBEDDING_DIM
    assert all(isinstance(x, float) for x in vector)
    # Un embedding real no es el vector cero.
    assert any(abs(x) > 1e-6 for x in vector)


@pytest.mark.integration
def test_embed_text_real_latency_under_100ms_when_warm() -> None:
    """RF/RNF: embeber una nota en < 100 ms en CPU (modelo ya cargado)."""
    embed_text("calentamiento del modelo")  # warmup: carga el modelo en Ollama
    start = time.perf_counter()
    embed_text("medición de latencia de un cuerpo de nota típico")
    elapsed_ms = (time.perf_counter() - start) * 1000.0
    assert elapsed_ms < 100.0, f"embed tardó {elapsed_ms:.1f} ms (objetivo < 100 ms)"


@pytest.mark.integration
def test_embed_similar_texts_closer_than_dissimilar() -> None:
    """Sanity semántica: dos textos afines tienen mayor similitud coseno."""

    def cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b, strict=True))
        na = sum(x * x for x in a) ** 0.5
        nb = sum(y * y for y in b) ** 0.5
        return dot / (na * nb)

    padel_a = embed_text("estrategia de captación para clubs de padel")
    padel_b = embed_text("plan para captar clubes de pádel con muchos socios")
    unrelated = embed_text("la fotosíntesis convierte luz solar en energía química")

    assert cosine(padel_a, padel_b) > cosine(padel_a, unrelated)
