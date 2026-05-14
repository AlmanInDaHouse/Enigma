"""Smoke tests para verificar que el paquete y la config arrancan limpios."""

from enigma import __version__
from enigma.config import settings


def test_version_string_present() -> None:
    """`enigma.__version__` es una cadena no vacía."""
    assert isinstance(__version__, str)
    assert __version__


def test_settings_loads_with_defaults() -> None:
    """La instancia global `settings` se importa y trae defaults sensatos."""
    assert settings.ollama_host.startswith("http")
    assert settings.qdrant_port == 6333
    assert settings.whisper_language == "es"
    assert settings.api_port == 8077
