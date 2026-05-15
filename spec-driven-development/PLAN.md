# Enigma — Plan Técnico (PLAN)

> **Versión:** 1.0 · **Estado:** Borrador inicial
> **Propósito:** describe **cómo** se implementa lo definido en `SPEC.md`, respetando `CONSTITUTION.md`.

---

## 1. Stack tecnológico

| Capa | Tecnología | Justificación |
|---|---|---|
| Lenguaje principal | **Python 3.11+** | Ecosistema maduro para IA/NLP; mismo lenguaje en todo el pipeline |
| Transcripción | **faster-whisper** (CTranslate2) | 4× más rápido que whisper original; CPU-friendly; soporta español |
| Diarización | **pyannote.audio 4.x** + `speaker-diarization-community-1` | Estándar de facto. Requiere token HuggingFace y FFmpeg *shared build* (torchcodec carga audio vía DLLs de FFmpeg) |
| LLM local | **Ollama** + Qwen 2.5 7B (default) | API REST sencilla, gestión de modelos automática. Llama 3.1 8B sigue siendo compatible si su pull queda desbloqueado (ver TASKS T-006) |
| Embeddings | **Ollama** con `nomic-embed-text` | Local, 768 dim, buen español |
| Vector DB | **Qdrant** (Docker) | Robusto, filtrado por metadatos, REST + gRPC |
| Orquestación IA | **LlamaIndex** | Mejor abstracción para retrieval + agentes que LangChain para este caso |
| API interna | **FastAPI** | Tipado con Pydantic, docs auto, async nativo |
| Cola de trabajos | **SQLite + APScheduler** | Suficiente para 6 usuarios; cero infraestructura extra |
| Knowledge store | **Obsidian Vault** en Git | Markdown plano, versionado, sin lock-in |
| CLI | **Typer** | Builds CLIs claras a partir de funciones |
| Testing | **pytest + pytest-asyncio** | Estándar |
| Linting / format | **ruff + black + mypy** | Calidad sin discusiones |
| Empaquetado | **Docker Compose** | Un comando para levantar Qdrant + workers |
| Dependencias Python | **uv** o **poetry** | uv preferido por velocidad |

## 2. Arquitectura por componentes

```
┌─────────────────────────────────────────────────────────────────────┐
│                          Usuario (CLI / Obsidian)                    │
└───────────────┬──────────────────────────────────────┬──────────────┘
                │                                      │
                ▼                                      ▼
        ┌──────────────┐                        ┌────────────────┐
        │   enigma-cli │                        │  Obsidian.app  │
        └──────┬───────┘                        └────────┬───────┘
               │                                         │ (lee/escribe MD)
               ▼                                         │
        ┌──────────────────────────────────┐             │
        │   FastAPI (puerto 8077)          │             │
        └─────┬────────────┬──────────┬────┘             │
              │            │          │                  │
              ▼            ▼          ▼                  │
        ┌─────────┐  ┌──────────┐ ┌──────────┐           │
        │ Ingestor│  │Extractor │ │  Agente  │           │
        │ (audio) │  │  (LLM)   │ │  (RAG)   │           │
        └────┬────┘  └─────┬────┘ └─────┬────┘           │
             │             │            │                │
             ▼             ▼            │                │
        ┌────────────────────────┐      │                │
        │   Procesador NLP       │      │                │
        │ Whisper → Diarización  │      │                │
        └──────────┬─────────────┘      │                │
                   │                    │                │
                   ▼                    ▼                ▼
        ┌──────────────────────────────────────────────────┐
        │   Vault Writer  (escribe .md en Obsidian Vault)  │
        └──────────────────────┬───────────────────────────┘
                               │
                               ▼
        ┌──────────────────────────────────────────────────┐
        │   Vault de Obsidian (carpeta Git)                │
        └──────────────────────┬───────────────────────────┘
                               │ (file watcher)
                               ▼
        ┌──────────────────────────────────────────────────┐
        │   Vectorizer  →  Qdrant (puerto 6333)            │
        └──────────────────────────────────────────────────┘
```

### 2.1 Componentes

| Componente | Responsabilidad | Entradas | Salidas |
|---|---|---|---|
| **enigma-cli** | UX en línea de comandos | argumentos | llamadas a la API |
| **API (FastAPI)** | Orquestación HTTP, expone endpoints REST | HTTP | dispatch a workers |
| **Ingestor** | Recibe audio, lo registra como `Call`, dispara procesamiento | fichero de audio | `call_id` |
| **Procesador NLP** | Transcribe + diariza | audio | `Transcript` con segmentos |
| **Extractor** | Convierte transcript en notas atómicas vía LLM | `Transcript` | lista de `Note` |
| **Vault Writer** | Persiste notas como `.md` en el Vault | `Note[]` | ficheros en disco |
| **Vectorizer** | Embebe notas y *upsertea* en Qdrant | `Note` | vectores en Qdrant |
| **Agente** | RAG + análisis transversal | consulta o tarea | respuesta con citas |
| **File watcher** | Detecta cambios en el Vault y dispara re-vectorización | eventos FS | calls a Vectorizer |

## 3. Estructura del repositorio

```
Enigma_V3/
├── README.md
├── CLAUDE.md                       # contexto persistente para Claude Code
├── .gitignore
├── .env.example
├── pyproject.toml
├── docker-compose.yml
├── spec-driven-development/        # documentación SDD viva (lectura obligada cada sesión)
│   ├── CONSTITUTION.md             # principios inmutables
│   ├── SPEC.md                     # qué construimos
│   ├── PLAN.md                     # cómo lo construimos (este fichero)
│   ├── TASKS.md                    # desglose accionable por fases
│   ├── docs/
│   │   ├── data-model.md
│   │   ├── architecture.md
│   │   └── setup-windows.md
│   ├── prompts/
│   │   └── initial-prompt.md       # prompt de arranque de sesión
│   └── specs/
│       └── 001-mvp-core/
│           └── spec.md             # spec detallada del primer feature
├── src/
│   └── enigma/
│       ├── __init__.py
│       ├── cli.py                  # Typer entrypoint (version, ingest, list)
│       ├── api.py                  # FastAPI app
│       ├── config.py               # Pydantic Settings
│       ├── pipeline.py             # orquestación end-to-end audio → Vault
│       ├── search.py               # búsqueda semántica top-k (enigma search)
│       ├── db/                     # SQLite shared infra (calls, transcripts, jobs)
│       │   ├── sqlite.py           # get_connection + init_schema
│       │   └── calls.py            # CRUD para la tabla `calls`
│       ├── models/                 # Pydantic models
│       │   ├── call.py
│       │   ├── transcript.py
│       │   └── note.py
│       ├── ingest/
│       │   ├── audio.py            # registro de Call + copia de audio
│       │   ├── transcriber.py      # faster-whisper wrapper + assign_speakers
│       │   └── diarizer.py         # pyannote.audio (quién habla cuándo)
│       ├── extract/
│       │   ├── prompts.py          # plantilla system+user para el LLM
│       │   ├── chunker.py          # particionado del transcript con overlap
│       │   └── extractor.py        # LLM → notas atómicas
│       ├── vault/
│       │   ├── writer.py           # escribe .md (notas + índice de llamada)
│       │   ├── frontmatter.py      # genera YAML + renderiza Markdown
│       │   ├── reader.py           # lee notas del Vault para listados
│       │   └── linker.py           # propone wikilinks
│       ├── vector/
│       │   ├── qdrant_client.py    # CRUD sobre la colección Qdrant
│       │   ├── embedder.py         # embeddings con nomic-embed-text
│       │   ├── reranker.py         # reranking con cross-encoder local
│       │   └── reindexer.py        # reindexado completo Vault → Qdrant
│       ├── agent/
│       │   ├── rag.py                # pipeline RAG (retrieve + LLM + citas)
│       │   ├── prompts.py            # prompts del RAG / agente
│       │   ├── decisions.py          # extracción de decisiones → decisions.md
│       │   ├── themes.py             # ideas recurrentes → recurring-themes.md
│       │   ├── serendipity.py        # conexiones no obvias → serendipity.md
│       │   ├── summarizer.py
│       │   ├── contradictions.py
│       │   └── tasks_extractor.py
│       └── workers/
│           └── watcher.py          # observa el Vault
├── vault/                          # Obsidian Vault — repo separado (Enigma-Vault.git) clonado aquí. Gitignored.
│   ├── .obsidian/
│   ├── inbox/                      # notas recién extraídas, pendientes de revisión
│   ├── notes/                      # notas atómicas validadas
│   ├── calls/                      # nota índice por llamada
│   └── people/                     # notas-entidad para personas mencionadas
├── tests/
│   ├── unit/
│   ├── integration/
│   └── fixtures/
│       └── audios/
└── scripts/
    ├── bootstrap.ps1               # setup Windows
    ├── bootstrap.sh                # setup Unix
    └── reindex.py                  # reconstruir Qdrant desde el Vault
```

**Notas sobre el layout:**
- Los ficheros canónicos del proyecto (`pyproject.toml`, `docker-compose.yml`, `.env.example`, `.gitignore`, `README.md`) viven en la **raíz** del repo, donde las herramientas Python (uv/ruff/pytest) los esperan.
- La documentación SDD vive en `spec-driven-development/` como subdirectorio dedicado. `CLAUDE.md` apunta a esta ruta para los specs canónicos.
- El **Vault de Obsidian es un repo Git independiente** (ver `docs/setup-windows.md` y §4.4). Se clona dentro de `vault/`, pero ese directorio está en `.gitignore` de este repo — no se versiona aquí.

## 4. Decisiones técnicas clave

### 4.1 ¿Por qué LlamaIndex y no LangChain?
LlamaIndex tiene mejor primitivas para *retrieval* puro (que es el 80% de lo que hace Enigma). LangChain es más generalista pero más pesado y con APIs cambiantes. Si en v2 necesitamos agentes complejos multi-tool, reevaluamos.

> **Desviación (T-302, 2026-05-15):** el pipeline RAG de Fase 3 se implementó **sin LlamaIndex**. El *retrieval* (embed query → `nomic-embed-text` → búsqueda en Qdrant) ya estaba resuelto con código propio en Fases 2-3 (`vector/`, `search.py`), y la generación es una única llamada a `ollama.chat` con un prompt que fuerza citas `[[wikilink]]`. Envolver esas piezas en `QdrantVectorStore` + `QueryEngine` de LlamaIndex añadiría una capa de abstracción sobre componentes que ya controlamos, sin aportar valor para un equipo de 6 personas — y CONSTITUTION §6 exige justificar cada dependencia. El flujo RAG vive en `src/enigma/agent/rag.py` + `agent/prompts.py`. LlamaIndex queda como dependencia no usada; se reevaluará si Fase 4 (agente multi-tool) lo necesita.

### 4.2 ¿Por qué Qdrant y no PGVector / Chroma?
- **Chroma:** embebido y simple, pero filtrado por metadatos limitado.
- **PGVector:** requiere Postgres, más infraestructura.
- **Qdrant:** estándalone, filtros ricos, rendimiento probado, REST cómoda.

Como **fallback configurable** en v1, ChromaDB embebido para usuarios que no quieran Docker.

### 4.3 ¿Por qué SQLite + APScheduler y no Celery/Redis?
Para 6 usuarios y ~10 calls/día, una cola de trabajos en SQLite con APScheduler es suficiente, no añade dependencias, no requiere Redis. La Constitution dicta simplicidad.

### 4.4 ¿Cómo se sincroniza el Vault entre los 6 usuarios?
**Git** con flujo automatizado:
- Plugin `obsidian-git` en cada cliente, configurado para hacer `pull` cada 10 min y `commit + push` automático.
- Un repo dedicado para el Vault (`Enigma-Vault.git`), separado del repo de código.
- Conflictos se resuelven por merge automático en `.md` (raros) y revisión manual cuando ocurren.
- El procesador NLP corre **en una sola máquina** (la del admin o un mini-servidor) que hace `push` al Vault tras escribir notas.

### 4.5 Idempotencia
Cada nota lleva en su frontmatter:
- `id`: UUIDv5 derivado de `call_id` + `chunk_id` (determinista)
- `content_hash`: SHA-256 del cuerpo
- `source_id`: referencia al call+timestamp original

Reingestar la misma llamada produce los mismos `id`s; el Vault Writer hace *upsert* por `id`.

### 4.6 Prompt engineering del extractor
Plantilla en `src/enigma/extract/prompts.py`. Estrategia:
1. Chunking del transcript por ventanas de ~1.500 tokens con overlap.
2. Por cada chunk: prompt que pide JSON con `[{title, body, tags, related_concepts}]`.
3. Validación con Pydantic; reintentos hasta 3 si el JSON falla.
4. Deduplicación posterior por similitud semántica > 0.92.

### 4.7 Detección de wikilinks
Cuando se crea una nota:
1. Se embebe su cuerpo.
2. Se buscan en Qdrant las top-5 notas más cercanas (umbral 0.78).
3. Para cada candidato, un LLM evalúa si el enlace es semánticamente válido (no solo cercanía).
4. Los que pasan se añaden como `[[wikilink]]` en sección dedicada.

### 4.8 Reranking del retrieval (T-304)
La búsqueda vectorial usa embeddings *bi-encoder* (`nomic-embed-text`): rápida pero la query y el documento se codifican por separado. Para mejorar la calidad del top-k del RAG se añade un paso de reranking **opcional** con un *cross-encoder* local — `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, multilingüe, vía `sentence-transformers`.

- **Por qué un cross-encoder y no más embeddings:** el cross-encoder procesa el par `(query, cuerpo)` junto, capturando relevancia que dos embeddings independientes no ven. No es indexable, por eso solo se aplica sobre un pool ya recuperado (`rerank_candidate_pool`, default 20) y se truncan las `top_k` mejores.
- **Dependencia (CONSTITUTION §6):** `sentence-transformers` es open source y 100% local — el modelo se descarga una vez de HuggingFace (~120 MB) y luego corre offline, igual que los modelos de Ollama o pyannote. No introduce ninguna API externa en el flujo.
- **Opcional:** `rerank_enabled = False` por defecto. El RAG funciona sin reranking; se activa vía `.env` cuando el corpus crece y la calidad del top-k lo justifica.
- Implementación en `src/enigma/vector/reranker.py`; cableado en `agent/rag.py::answer_question`.

### 4.9 Detección de contradicciones (T-404)
Una contradicción es un par de notas que afirman algo opuesto sobre la misma entidad. Comparar las N²/2 parejas con el LLM es inviable.

- **Pares candidatos por proximidad semántica:** una contradicción solo puede darse entre notas del mismo tema. Para cada nota se buscan sus top-k vecinos en Qdrant (mismo patrón que la detección de wikilinks, §4.7) y solo esos pares — deduplicados (A-B = B-A) y por encima de `contradiction_similarity_threshold` (0.80) — pasan por el juicio del LLM. Coste: **O(N·k)** llamadas LLM en vez de O(N²).
- **Juicio del LLM:** para cada par candidato, el LLM responde JSON `{"contradiction": bool, "explanation": str}`. Conservador: ante la duda, `false`.
- Las contradicciones confirmadas se agregan en `vault/contradictions.md` (índice MOC en la raíz del Vault, regenerable con `enigma contradictions`). Implementación en `src/enigma/agent/contradictions.py`. Requiere el Vault indexado en Qdrant.

### 4.10 Ideas recurrentes (T-405)
Una idea recurrente es un tema que reaparece en varias notas a lo largo del tiempo.

- **Clustering por componentes conexas:** se construye el grafo de similitud (aristas = vecinos Qdrant sobre `recurring_similarity_threshold`) y sus componentes conexas — vía union-find puro, sin dependencias — son los clusters temáticos (*single-linkage clustering*). Se descartan K-means (necesita k a priori) y HDBSCAN/sklearn (dependencia nueva).
- **Criterio de recurrencia:** un cluster es idea recurrente solo si tiene ≥ `recurring_min_notes` (3) notas Y provienen de ≥ `recurring_min_calls` (2) llamadas distintas. Lo segundo es el componente temporal: varias notas de una sola llamada son una discusión puntual, no recurrencia.
- **Umbral:** `recurring_similarity_threshold = 0.68`. `nomic-embed-text` tiene un suelo de similitud alto (~0.60); medido en T-405, las notas del mismo tema caen en ~0.69-0.77 y el ruido en ~0.60-0.63 — de ahí 0.68 (más bajo que el 0.80 de contradicciones, que comparan afirmaciones casi idénticas).
- El LLM nombra cada cluster cualificado; el resultado se agrega en `vault/recurring-themes.md` (`enigma themes`). Implementación en `src/enigma/agent/themes.py`.

### 4.11 Serendipia: conexiones no obvias (T-406)
El "modo serendipia" propone conexiones sorprendentes entre notas distantes — lo opuesto a los wikilinks (§4.7), que enlazan notas obvias.

- **Banda de similitud media:** los pares candidatos no son los más similares (obvios, ya cubiertos por wikilinks) ni los más lejanos (ruido), sino los de una **ventana** `[serendipity_min_similarity, serendipity_max_similarity)` = `[0.63, 0.74)`. Mantenerse por debajo del umbral de wikilink (0.78) aproxima "conexiones nuevas".
- **Juicio del LLM:** para cada par de la banda, el LLM decide si unirlas produce una idea genuinamente valiosa (analogía, causa común, oportunidad). Muy selectivo: ante la duda, `false`.
- **Tope:** se confirman como máximo `serendipity_max_suggestions` (5) conexiones — los pares se evalúan en orden determinista y el proceso se detiene al llegar a 5. Resultado en `vault/serendipity.md` (`enigma serendipity`). Implementación en `src/enigma/agent/serendipity.py`.

## 5. Modelo de despliegue

Una sola máquina principal (la del admin) corre:
- Qdrant (Docker)
- Ollama (servicio local en puerto 11434)
- API de Enigma (puerto 8077)
- File watcher

Los demás usuarios:
- Instalan Obsidian
- Clonan el Vault
- Configuran `obsidian-git`
- **Opcional:** la CLI de Enigma apuntando a la API del admin para ingerir audio

## 6. Configuración

Variables en `.env` (ver `.env.example`):

```env
# Paths
ENIGMA_VAULT_PATH=C:/Users/manul/Enigma_V3/vault
ENIGMA_DATA_PATH=C:/Users/manul/Enigma_V3/data

# Ollama
OLLAMA_HOST=http://localhost:11434
OLLAMA_LLM_MODEL=qwen2.5:7b
OLLAMA_EMBED_MODEL=nomic-embed-text

# Qdrant
QDRANT_HOST=localhost
QDRANT_PORT=6333
QDRANT_COLLECTION=enigma_notes

# Whisper
WHISPER_MODEL=large-v3
WHISPER_DEVICE=auto   # cpu | cuda | auto
WHISPER_LANGUAGE=es

# API
API_HOST=127.0.0.1
API_PORT=8077

# Behavior
LINK_SIMILARITY_THRESHOLD=0.78
DEDUP_SIMILARITY_THRESHOLD=0.92
```

## 7. Roadmap por fases

Detalle en `TASKS.md`. Resumen:

- **Fase 0 — Bootstrap (1 semana):** repo, CI, Docker, dependencias, "hello world" del pipeline.
- **Fase 1 — MVP audio → notas (3 semanas):** ingest → transcribe → extract → write a `.md`. Sin links, sin búsqueda.
- **Fase 2 — Grafo y vectorización (2 semanas):** Qdrant, wikilinks automáticos, file watcher.
- **Fase 3 — Búsqueda semántica + RAG (2 semanas):** consulta en lenguaje natural con citas.
- **Fase 4 — Agente analítico (3 semanas):** resúmenes, decisiones, contradicciones, tareas.
- **Fase 5 — Endurecimiento (2 semanas):** packaging Windows, docs, onboarding del equipo.

Total estimado: **~13 semanas** de trabajo enfocado.

## 8. Riesgos técnicos y mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| Whisper falla con audio de baja calidad | Media | Alto | Soporte para preprocesado (denoise, normalización) |
| LLM local extrae notas pobres | Media | Alto | Iterar prompts, fallback a modelos mayores (70B) o cloud opcional |
| Conflictos Git en el Vault | Media | Medio | Estrategia de merge `.gitattributes`; carpeta `inbox/` separada por usuario |
| Qdrant deriva del Vault | Baja | Alto | Script `reindex.py` reconstruye Qdrant desde cero |
| Rendimiento en CPU sin GPU | Alta | Medio | Modelos pequeños por defecto (Whisper medium, Llama 8B); GPU opcional |

## 9. Definición de "Done" para cada feature

Un feature no se da por terminado hasta que:
- [ ] Tiene tests unitarios e integración (cobertura ≥ 70% del código nuevo)
- [ ] `ruff`, `black`, `mypy` pasan sin warnings
- [ ] `SPEC.md` o spec del feature actualizada
- [ ] `TASKS.md` marca las tareas como done
- [ ] Funciona end-to-end con un audio de prueba en español
- [ ] Hay un párrafo en `README.md` que lo describe
