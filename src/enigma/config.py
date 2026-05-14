"""Pydantic Settings para Enigma.

Carga configuración desde `.env` en la raíz del proyecto (si existe) o de
variables de entorno. Los defaults son sensatos para desarrollo local en
Windows; en producción se sobrescriben vía `.env`.
"""

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Raíz del repo (.../Enigma_V3/), independiente del cwd desde el que se importe.
PROJECT_ROOT: Path = Path(__file__).resolve().parent.parent.parent


class Settings(BaseSettings):
    """Configuración global del proyecto Enigma."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ── Paths ───────────────────────────────────────────────────────────
    enigma_vault_path: Path = PROJECT_ROOT / "vault"
    enigma_data_path: Path = PROJECT_ROOT / "data"

    # ── Ollama (LLM + embeddings) ───────────────────────────────────────
    ollama_host: str = "http://localhost:11434"
    ollama_llm_model: str = "llama3.1:8b"
    ollama_embed_model: str = "nomic-embed-text"
    ollama_timeout: int = 120

    # ── Qdrant (vector DB) ──────────────────────────────────────────────
    qdrant_host: str = "localhost"
    qdrant_port: int = 6333
    qdrant_collection: str = "enigma_notes"
    qdrant_api_key: str | None = None

    # ── Whisper (transcripción) ─────────────────────────────────────────
    whisper_model: str = "large-v3"
    whisper_device: str = "auto"
    whisper_language: str = "es"
    whisper_compute_type: str = "int8"

    # ── Diarización (pyannote) ──────────────────────────────────────────
    diarization_enabled: bool = True
    pyannote_auth_token: str | None = None

    # ── API REST interna ────────────────────────────────────────────────
    api_host: str = "127.0.0.1"
    api_port: int = 8077
    api_log_level: str = "info"

    # ── Extractor (LLM → notas atómicas) ────────────────────────────────
    extract_chunk_tokens: int = 1500
    extract_chunk_overlap: int = 200
    extract_max_notes_per_call: int = 50

    # ── Linker (creación automática de wikilinks) ───────────────────────
    link_similarity_threshold: float = 0.78
    link_top_k_candidates: int = 5
    link_llm_validation: bool = True

    # ── Deduplicación intra-llamada ─────────────────────────────────────
    dedup_similarity_threshold: float = 0.92

    # ── Logging ─────────────────────────────────────────────────────────
    log_level: str = "INFO"
    log_format: str = "json"

    # ── Modo desarrollo ─────────────────────────────────────────────────
    dev_mode: bool = False


settings = Settings()
"""Instancia singleton importable: `from enigma.config import settings`."""
