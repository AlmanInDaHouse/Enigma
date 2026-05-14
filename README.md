# Enigma 🧩

[![CI](https://github.com/AlmanInDaHouse/Enigma/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/AlmanInDaHouse/Enigma/actions/workflows/ci.yml)

> **Segundo cerebro conversacional para equipos pequeños.**
> Cada llamada → notas atómicas conectadas en Obsidian + búsqueda semántica local.

---

## ¿Qué es Enigma?

Enigma transforma las llamadas de un equipo (≤ 6 personas) en **conocimiento estructurado y conectado**. Graba o ingiere audio, lo transcribe localmente, extrae **notas atómicas estilo Zettelkasten** mediante un LLM local, las enlaza al grafo existente en Obsidian, y las hace consultables semánticamente.

Todo **local**, todo **privado**, todo **open source**.

```
🎙️  Llamada
   ↓
📝  Transcripción (faster-whisper)
   ↓
💡  Extracción atómica (Llama 3 local)
   ↓
📚  Notas en Obsidian con [[wikilinks]]
   ↓
🔍  Búsqueda semántica (Qdrant)
   ↓
🤖  Agente: resúmenes, decisiones, contradicciones
```

---

## Spec-Driven Development

Este proyecto se desarrolla siguiendo el método **Spec-Driven Development**. Los documentos canónicos son:

| Documento | Propósito |
|---|---|
| [`CONSTITUTION.md`](CONSTITUTION.md) | Principios inmutables (local-first, atomicidad, etc.) |
| [`SPEC.md`](SPEC.md) | **Qué** se construye (funcional, casos de uso, RF/RNF) |
| [`PLAN.md`](PLAN.md) | **Cómo** se construye (arquitectura, stack, decisiones) |
| [`TASKS.md`](TASKS.md) | **Cuándo** se construye (desglose accionable por fases) |
| [`docs/data-model.md`](docs/data-model.md) | Modelo de datos detallado |
| [`docs/architecture.md`](docs/architecture.md) | Diagramas y flujos |
| [`docs/setup-windows.md`](docs/setup-windows.md) | Guía de instalación |

**Regla:** ningún PR de código sin actualizar los specs si toca su contenido.

---

## Stack

- **Python 3.11+** · orquestación
- **faster-whisper** · transcripción local
- **pyannote.audio** · diarización
- **Ollama** (Llama 3.1 / nomic-embed-text) · LLM y embeddings
- **Qdrant** · base vectorial
- **LlamaIndex** · RAG y orquestación IA
- **FastAPI + Typer** · API y CLI
- **Obsidian + Git** · vault y sincronización

---

## Quick start

Ver guía detallada en [`docs/setup-windows.md`](docs/setup-windows.md).

```powershell
git clone https://github.com/AlmanInDaHouse/Enigma.git Enigma_V3
cd Enigma_V3
docker compose up -d qdrant
ollama pull llama3.1:8b && ollama pull nomic-embed-text
uv venv && .venv\Scripts\Activate.ps1
uv pip install -e ".[dev]"
copy .env.example .env
enigma init
enigma ingest path\to\audio.m4a
enigma ask "¿qué decidimos sobre X?"
```

---

## Estado

🚧 **Fase 0 — Bootstrap.** Specs definidas, código aún por escribir.

Progreso en [`TASKS.md`](TASKS.md).

---

## Licencia

Privado · uso interno del equipo.
