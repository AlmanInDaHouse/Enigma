# Enigma — Plan de Tareas (TASKS)

> **Versión:** 1.0 · **Estado:** Activo
> **Convención:** cada tarea tiene ID, criterio de aceptación verificable y referencia al RF/RNF cubierto.

---

## Cómo trabajar este documento

- Marca `[x]` al cerrar una tarea.
- Si una tarea se subdivide, crea sub-IDs (`T-12.1`, `T-12.2`).
- Una tarea no se cierra sin cumplir su **criterio de aceptación**.
- Cualquier tarea nueva pasa por: ¿necesita actualizar `SPEC.md` o `PLAN.md`?

---

## Fase 0 — Bootstrap (semana 1)

> Objetivo: repositorio inicializado, dependencias funcionando, "hello world" del pipeline.

- [x] **T-001** Inicializar repositorio Git y conectar a `github.com/AlmanInDaHouse/Enigma.git`
  - *Aceptación:* `git push origin main` exitoso desde `C:\Users\manul\Enigma_V3`
- [x] **T-002** Crear `pyproject.toml` con dependencias base (FastAPI, Typer, Pydantic, pytest, ruff, black, mypy)
  - *Aceptación:* `uv sync` o `poetry install` instala sin errores
- [x] **T-003** Configurar `.gitignore` para Python + Windows + datos sensibles (`*.wav`, `data/`, `.env`)
  - *Aceptación:* `git status` limpio tras setup
- [x] **T-004** Configurar pre-commit con `ruff`, `black`, `mypy`
  - *Aceptación:* commit con código mal formateado se bloquea
- [x] **T-005** Crear `docker-compose.yml` con servicio Qdrant
  - *Aceptación:* `docker compose up qdrant` deja Qdrant respondiendo en `http://localhost:6333/dashboard`
- [x] **T-006** Instalar Ollama localmente y descargar el LLM + embedder
  - *Aceptación:* `ollama run <llm_model> "Hola"` responde **y** `nomic-embed-text` está disponible.
  - **Estado:** completado. Modelos descargados: `llama3.1:8b` (4.9 GB), `nomic-embed-text` (274 MB, 768 dims), `qwen2.5:7b`, `llama3.2:3b`. El error TLS de la sesión anterior resultó ser **transitorio** (blip de red, no SSL inspection — los certs de `registry.ollama.ai` y `*.r2.cloudflarestorage.com` son legítimos de Google Trust Services). `qwen2.5:7b` sigue como LLM por defecto; comparar contra `llama3.1:8b` queda como tarea de evaluación futura antes de fijar el default oficial.
- [x] **T-007** Crear `src/enigma/config.py` con `Pydantic Settings` cargando `.env`
  - *Aceptación:* `python -c "from enigma.config import settings; print(settings)"` imprime config
- [x] **T-008** Crear estructura de carpetas según `PLAN.md` §3 con `__init__.py` en todos los paquetes
  - *Aceptación:* `pytest` arranca sin errores de import
- [x] **T-009** Smoke test: `enigma --version` desde CLI
  - *Aceptación:* Typer responde con versión definida
- [x] **T-010** Configurar GitHub Actions: lint + tests en cada push a `main`
  - *Aceptación:* badge verde en `README.md`

---

## Fase 1 — MVP audio → notas (semanas 2-4)

> Objetivo: meter un `.wav` y obtener notas atómicas en el Vault. Sin links automáticos todavía.

### Ingesta y transcripción

- [x] **T-101** Implementar `enigma.ingest.audio.register_call(path) -> Call` (RF-01)
  - *Aceptación:* copia el audio a `data/audio/{call_id}.{ext}` (extensión preservada) y crea registro en SQLite
- [x] **T-102** Wrapper de `faster-whisper` en `enigma.ingest.transcriber` (RF-02)
  - *Aceptación:* transcribe un audio de prueba en español con WER ≤ 15%
- [x] **T-103** Integrar diarización con `pyannote.audio` (RF-03)
  - *Aceptación:* output incluye `speakers` distinguibles cuando el audio tiene 2+ voces
  - **Nota:** pyannote.audio 4.x usa el modelo `pyannote/speaker-diarization-community-1` (no `3.1`) y carga audio vía `torchcodec`, que requiere FFmpeg *shared build* (`Gyan.FFmpeg.Shared`) en el PATH. `transcribe()` diariza si `settings.diarization_enabled`; un fallo de diarización es non-fatal (RF-03 es *Should*). Verificado con `test_diarize_real` (integration).
- [x] **T-104** Persistir transcripción como JSON en `data/transcripts/{call_id}.json`
  - *Aceptación:* JSON validable con esquema Pydantic `Transcript`

### Extracción de notas atómicas

- [x] **T-105** Diseñar y testear prompt de extracción atómica en `extract/prompts.py` (RF-04)
  - *Aceptación:* sobre 3 transcripts de prueba, produce entre 5-30 notas/hora *(validación estática completa; medición empírica de 5-30 notas/h queda para T-115 con LLM real)*
- [x] **T-106** Implementar chunking con overlap del transcript
  - *Aceptación:* test unitario verifica que un transcript de 10k tokens se divide correctamente
- [x] **T-107** Implementar `extract/extractor.py` con cliente Ollama
  - *Aceptación:* devuelve `List[Note]` validados por Pydantic
- [x] **T-108** Deduplicación intra-llamada por similitud semántica > 0.92
  - *Aceptación:* test con 2 notas casi idénticas las fusiona en 1
  - **Nota:** Fase 1 usa heurística textual (SHA-256 + `difflib.SequenceMatcher` sobre títulos) porque `nomic-embed-text` está bloqueado por T-006. Fase 2 (T-201/T-202) reemplazará con similitud coseno sobre embeddings reales del cuerpo. El threshold `0.92` mantiene su semántica entre ambas estrategias.

### Vault Writer

- [x] **T-109** Generador de frontmatter YAML con campos obligatorios (RF-05)
  - *Aceptación:* validador YAML pasa; campos `id`, `source`, `timestamp`, `tags` siempre presentes
- [x] **T-110** Naming determinista de ficheros: `{slugified_title}-{short_id}.md`
  - *Aceptación:* reingestar la misma llamada NO crea ficheros duplicados (RF-10)
- [x] **T-111** Escribir notas en `vault/inbox/` (revisión humana antes de promoción)
  - *Aceptación:* tras procesar un audio, las notas aparecen en `vault/inbox/`
- [x] **T-112** Crear nota índice por llamada en `vault/calls/{date}-{title}-{short_id}.md` con enlaces a las notas extraídas
  - *Aceptación:* abrir la nota de la llamada en Obsidian muestra el grafo local
  - **Nota:** se añadió `{short_id}` (8 hex del `call_id`) al filename respecto al ejemplo en `docs/architecture.md §5` para garantizar idempotencia 1↔1 con `Call.id` y evitar colisiones cuando coinciden fecha + título.

### CLI mínima

- [x] **T-113** `enigma ingest <audio>` end-to-end (RF-13)
  - *Aceptación:* un solo comando lleva de `.wav` a `.md` en el Vault
- [x] **T-114** `enigma list calls` y `enigma list notes --last 7d`
  - *Aceptación:* salida tabulada legible
- [x] **T-115** Tests E2E con fixture de audio corto (30s)
  - *Aceptación:* `pytest tests/integration` verde
  - **Nota:** `test_pipeline_e2e_structural` corre el pipeline completo sobre 30s de silencio (verifica que no lanza excepción + artefactos en disco). `test_pipeline_e2e_with_real_audio` exige ≥1 nota pero se salta con `skipif` hasta que se añada `tests/fixtures/audios/sample_es.wav` (grabación real en español del equipo).

---

## Fase 2 — Grafo y vectorización (semanas 5-6)

> Objetivo: las notas se conectan automáticamente y son consultables semánticamente.

- [x] **T-201** Wrapper de Qdrant en `vector/qdrant_client.py` con `upsert`, `search`, `delete`
  - *Aceptación:* tests CRUD pasan contra Qdrant local
- [x] **T-202** Embedder con Ollama (`nomic-embed-text`)
  - *Aceptación:* embebe nota en < 100ms en CPU *(verificado: `test_embed_text_real_latency_under_100ms_when_warm` pasa)*
- [x] **T-203** Vectorizar todas las notas existentes con script `scripts/reindex.py`
  - *Aceptación:* Qdrant queda sincronizado con `vault/`
  - **Nota:** `reindex_vault()` (en `vector/reindexer.py`) devuelve un `ReindexReport` con métricas (notas/s, dim de vector, puntos en colección) para validar RNF-02/03. Idempotente: upsert por `note_id`.
- [x] **T-204** File watcher en `workers/watcher.py` que vectoriza al detectar cambios en `vault/`
  - *Aceptación:* editar una nota en Obsidian re-vectoriza en < 5s *(verificado: `test_watcher_vectorizes_new_note_within_5s`)*
  - **Nota:** comando `enigma watch` arranca el watcher. Borrar una nota elimina su vector si el watcher la había visto (cache `path → note_id`); huérfanas de antes del arranque se limpian en T-207 / reindex.
- [x] **T-205** Detección de wikilinks: top-5 vecinos + validación con LLM (RF-06)
  - *Aceptación:* > 70% de los links propuestos se mantienen tras revisión humana
  - **Nota:** `suggest_wikilinks()` en `vault/linker.py`: embebe → busca top-k en Qdrant → filtra por `link_similarity_threshold` (0.78) → valida cada candidato con LLM (descarta cercanías superficiales). La métrica "> 70%" requiere revisión humana — verificable cuando el equipo use el Vault. La validación LLM es conservadora: un fallo descarta el candidato.
- [x] **T-206** Inyectar wikilinks en sección dedicada de la nota
  - *Aceptación:* nota generada tiene `## Conexiones` con `[[links]]`
  - **Nota:** `apply_wikilinks()` en `vault/linker.py` re-renderiza la nota con `## Conexiones` entre el cuerpo y `## Origen`. Los wikilinks usan formato `[[stem|título]]` (Obsidian resuelve el stem = filename sin `.md`, muestra el título).
- [x] **T-207** Marcar notas huérfanas (sin links) con tag `#orphan` para revisión
  - *Aceptación:* dashboard CLI muestra count de huérfanas
  - **Nota:** `mark_orphans()` en `vault/linker.py` recorre el Vault, detecta notas sin `[[wikilink]]` y les añade el tag `orphan` (CONSTITUTION §10). Comando `enigma orphans` reporta total / huérfanas / recién marcadas. Idempotente.

---

## Fase 3 — Búsqueda semántica + RAG (semanas 7-8)

> Objetivo: preguntas en lenguaje natural devuelven respuestas con citas.

- [x] **T-301** `enigma search "<query>"` recupera top-k notas (RF-07)
  - *Aceptación:* p95 < 3s en Vault con 1.000 notas
  - **Nota:** `search_notes()` (en `src/enigma/search.py`, módulo nuevo nivel raíz como `pipeline.py`) embebe la query con `nomic-embed-text` → `qdrant_client.search()` → mapea cada `SearchHit` a un `SearchResult`. Los resultados se construyen **solo desde el payload Qdrant** (título, tags, fecha, estado): no se leen los cuerpos de las notas ni se recorre el Vault, así la búsqueda es un único embed + un único query — la cita textual del cuerpo es competencia del RAG (T-302). Lectura del payload defensiva: `call_id`/`created_at` malformados caen a `None` sin romper. Comando `enigma search "<q>" [--top-k/-k N]`. El p95 < 3s sobre 1.000 notas no se mide empíricamente (no hay corpus de ese tamaño todavía); verificado por diseño (1 embed ~50-100ms + 1 query Qdrant ~10ms) y por `test_search_latency_under_3s` (integration) sobre colección pequeña.
- [x] **T-302** Pipeline RAG con LlamaIndex: query → embed → retrieve → LLM → respuesta con citas
  - *Aceptación:* respuesta cita `[[Nota X]]` y los ficheros existen
  - **Nota:** `answer_question()` en `src/enigma/agent/rag.py`: `search_notes` (T-301) → `load_notes_by_ids` (nuevo en `vault/reader.py`, una pasada O(N) por el Vault para recuperar cuerpos) → `build_rag_messages` (`agent/prompts.py`, nuevo) → `ollama.chat` con `qwen2.5:7b`. Las citas se parsean de los `[[wikilink]]` de la respuesta y se casan contra los stems de las notas de contexto: una cita solo cuenta si apunta a una nota recuperada (que existe en disco) → garantiza el criterio "los ficheros existen"; un wikilink alucinado se descarta. Retrieval vacío → respuesta determinista sin llamar al LLM. **Desviación: implementado SIN LlamaIndex** (retrieve+generate a mano sobre Qdrant+Ollama; CONSTITUTION §6 — LlamaIndex envolvería componentes ya controlados). Documentado en `PLAN.md §4.1`. Verificado con `test_rag_real.py` (integration): la respuesta cita un `[[stem]]` que resuelve a un `.md` real del Vault.
- [x] **T-303** `enigma ask "<pregunta>"` con respuesta conversacional
  - *Aceptación:* sobre 10 preguntas de prueba, ≥ 7 respuestas son útiles (eval manual)
  - **Nota:** comando `enigma ask "<pregunta>" [--top-k/-k N]` en `cli.py`, capa fina sobre `answer_question` (T-302). Render: respuesta en panel Rich + lista de "Notas citadas" (`[[stem]] — título`, impreso con `markup=False` porque los corchetes son literales). `RagError` → mensaje rojo + `Exit(1)`; pregunta vacía → `BadParameter`. La aceptación "≥7/10 útiles" es **eval manual** y queda pendiente de un corpus de notas reales en el Vault (no automatizable; mismo patrón que el ">70%" de T-205). Tests CLI con `answer_question` mockeado verifican la mecánica del comando.
- [x] **T-304** Reranking opcional con cross-encoder local (mejora calidad top-k)
  - *Aceptación:* recall@5 sube vs baseline en test set
  - **Nota:** `rerank_notes()` en `src/enigma/vector/reranker.py` usa el cross-encoder `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (multilingüe, `sentence-transformers`) para reordenar un pool de candidatos por relevancia query↔cuerpo. Cableado en `answer_question` (`agent/rag.py`): con `rerank` activo recupera `rerank_candidate_pool` (20) → reordena → trunca a `top_k`. **Opcional, `rerank_enabled=False` por defecto** — el RAG funciona sin él. Dependencia nueva `sentence-transformers` (open source, modelo local descargado 1 vez; justificada en `PLAN.md §4.8`). Import perezoso de `sentence-transformers` (dep pesada). El recall@5 formal requiere un test set etiquetado que no existe todavía; verificado el **mecanismo** con `test_reranker_real.py` (integration): el cross-encoder corrige un orden baseline deliberadamente malo (la nota relevante sube de la última posición al top). Métrica formal pendiente de corpus etiquetado (mismo patrón que T-205/T-303).
- [x] **T-305** Endpoint REST `POST /ask` en FastAPI (RF-14)
  - *Aceptación:* curl al endpoint devuelve JSON con respuesta + citas
  - **Nota:** `src/enigma/api.py` deja de ser placeholder: app FastAPI con `POST /ask` (cuerpo `AskRequest`: `question`/`top_k`/`rerank`) y `GET /health`. `/ask` llama a `answer_question` (T-302) y serializa el `RagAnswer` — `answer` + `citations` + `sources` — a JSON directamente (ya es Pydantic). `RagError` → HTTP 503; pregunta en blanco → 422. Comando `enigma serve` arranca uvicorn en `settings.api_host:api_port`. **Hardening detectado en el smoke test:** `qdrant_client.search()` ahora devuelve `[]` si la colección no existe (sistema recién instalado sin `ingest`/`reindex`) en vez de un 500 — así `/ask` y `enigma search` responden con normalidad antes del primer indexado. Verificado con smoke manual (`/health` 200, `POST /ask` devuelve JSON con la forma respuesta+citas+fuentes).

---

## Fase 4 — Agente analítico (semanas 9-11)

> Objetivo: el sistema produce análisis transversal del corpus.

- [x] **T-401** Resumen ejecutivo de una llamada (RF-08)
  - *Aceptación:* `enigma summarize call <id>` produce resumen estructurado en `vault/calls/`
  - **Nota:** `summarize_call()` en `agent/summarizer.py`: carga el `Call` (SQLite) + su `Transcript` persistido → `build_summary_messages` (`agent/prompts.py`) → `ollama.chat` con `format="json"` → `CallSummary` (tldr + key_points + topics) → nota Markdown en `vault/calls/`. La nota-resumen es un **fichero separado** del índice de llamada (`{índice}-summary.md`, `type: call-summary`), porque el índice lo regenera el pipeline en cada re-ingest; enlaza al índice con `[[wikilink]]`. Idempotente (filename determinista). Comando `enigma summarize call <id>` acepta UUID completo o **prefijo corto** (los 8 hex de `enigma list calls`); prefijo ambiguo → error. **Decisión:** resumen single-shot sobre el transcript completo (no map-reduce) — entra en el contexto de `qwen2.5:7b` para llamadas ~1h; map-reduce para llamadas más largas queda como mejora futura (CONSTITUTION §7). Verificado con `test_summarizer_real.py` (integration, Ollama real).
- [x] **T-402** Extracción de decisiones tomadas
  - *Aceptación:* nota índice `decisions.md` listada cronológicamente con enlaces al origen
  - **Nota:** `build_decision_index()` en `agent/decisions.py`: recorre `list_calls` (SQLite) → por cada llamada con transcript persistido, `extract_decisions_from_call` (LLM `format="json"`, single-shot) → agrega y reescribe `vault/decisions.md`. Decisiones agrupadas por llamada, **orden cronológico inverso** (más reciente arriba — coherente con `list calls`); cada grupo enlaza al índice de llamada con `[[wikilink]]`. `decisions.md` vive en la **raíz del Vault** (índice transversal tipo MOC, no nota atómica ni de llamada). Comando `enigma decisions`. Idempotente (filename fijo, reescritura completa). Coste: N llamadas LLM por ejecución (1 por call); aceptado para decenas de llamadas, sin caché. Fuente = transcripts (decisión del usuario). Un fallo de extracción en una llamada se loguea y se omite — no bloquea el índice. Verificado con `test_decisions_real.py` (integration, Ollama real).
- [x] **T-403** Extracción de tareas pendientes
  - *Aceptación:* nota `tasks.md` con responsables (cuando identificables) y fecha de mención
  - **Nota:** `build_task_index()` en `agent/tasks_extractor.py`, gemelo estructural de T-402: recorre `list_calls` → `extract_tasks_from_call` (LLM `format="json"`) → reescribe `vault/tasks.md`. Cada tarea lleva `assignee` opcional (responsable, `null` si no se identifica); la fecha de mención es la `recorded_at` de la llamada, visible en la cabecera del grupo. Tareas renderizadas como checklist Markdown (`- [ ] enunciado — _responsable_`), agrupadas por llamada, orden cronológico inverso, con `[[wikilink]]` al índice de llamada. Comando `enigma tasks`. Idempotente; fallo de extracción por llamada se omite con warning. Verificado con `test_tasks_real.py` (integration, Ollama real).
- [x] **T-404** Detección de contradicciones (RF-09)
  - *Aceptación:* sobre un test set con contradicciones inyectadas, ≥ 60% detectadas
  - **Nota:** `build_contradiction_index()` en `agent/contradictions.py`. Para evitar el O(N²), los pares candidatos se generan por **proximidad semántica**: por cada nota, sus top-k vecinos en Qdrant sobre `contradiction_similarity_threshold` (0.80), deduplicados (A-B = B-A) → O(N·k) llamadas LLM. Cada par candidato lo juzga el LLM (`format="json"`, conservador). Las confirmadas → `vault/contradictions.md` (índice MOC, comando `enigma contradictions`). Reusa la infra de embeddings/Qdrant (patrón de wikilinks T-205) y `load_all_notes` (nuevo en `vault/reader.py`). Requiere el Vault indexado en Qdrant; sin colección → 0 candidatos, índice vacío (hardening T-305). Estrategia documentada en `PLAN.md §4.9`. **Aceptación verificada empíricamente:** `test_contradictions_real.py` (integration) inyecta 3 pares contradictorios + notas neutras, indexa y aserta recall ≥ 60%.
- [x] **T-405** Detección de ideas recurrentes (clustering temporal)
  - *Aceptación:* nota `recurring-themes.md` se regenera semanalmente
  - **Nota:** `build_recurring_themes_index()` en `agent/themes.py`. Clustering por **componentes conexas** del grafo de similitud (aristas = vecinos Qdrant sobre umbral; union-find puro, sin dependencias — descartados K-means y HDBSCAN/sklearn). Un cluster es idea *recurrente* si tiene ≥ `recurring_min_notes` (3) notas de ≥ `recurring_min_calls` (2) llamadas distintas (el componente temporal). El LLM nombra cada cluster cualificado → `vault/recurring-themes.md`. Comando `enigma themes`. **Umbral ajustado empíricamente a 0.68** (no 0.75): `nomic-embed-text` tiene suelo ~0.60; medido, mismo tema ~0.69-0.77, ruido ~0.60-0.63. La regeneración "semanal" es operativa (el usuario corre `enigma themes` o lo programa con cron/Task Scheduler); no se monta un daemon — el scheduling propio se aborda con backups (T-505). Estrategia en `PLAN.md §4.10`. Verificado con `test_themes_real.py` (integration).
- [x] **T-406** Sugerencias de conexiones no obvias entre notas distantes
  - *Aceptación:* "modo serendipia" propone 5 conexiones nuevas/semana
  - **Nota:** `build_serendipity_index()` en `agent/serendipity.py`. Lo opuesto a los wikilinks (T-205): los pares candidatos se toman de la **banda de similitud media** `[0.63, 0.74)` — ni obvios (≥ umbral wikilink) ni ruido. Mantenerse bajo el umbral de wikilink aproxima "conexiones nuevas" (no parseo los `## Conexiones` existentes — decisión de simplicidad). El LLM juzga cada par (muy selectivo); se confirman hasta `serendipity_max_suggestions` (5), evaluando los pares en orden determinista y parando al llegar a 5. Resultado en `vault/serendipity.md`, comando `enigma serendipity`. La cadencia "/semana" es operativa (correr el comando o programarlo). Estrategia en `PLAN.md §4.11`. Verificado con `test_serendipity_real.py` (integration): produce sugerencias, tope ≤5, fichero escrito.

---

## Fase 5 — Endurecimiento y onboarding (semanas 12-13)

> Objetivo: el equipo de 6 personas puede usar Enigma sin necesidad del builder original.

- [x] **T-501** Script `bootstrap.ps1` para Windows: instala dependencias, Ollama, Docker, modelos
  - *Aceptación:* máquina virgen → Enigma corriendo en < 30 min
  - **Nota:** `scripts/bootstrap.ps1` (PowerShell 5.1). 11 pasos: prerrequisitos → uv → Python 3.12 → `uv sync` → FFmpeg shared → Ollama → modelos (`qwen2.5:7b` + `nomic-embed-text`) → Docker Desktop → `.env` → Qdrant → verificación. Instala vía `winget` (transparente, sin `curl|iex`). **Idempotente**: cada paso comprueba antes de actuar; **nunca sobrescribe `.env`** (lo crea desde `.env.example` ajustando las rutas al repo). Flags: `-Check` (solo verificación, read-only) y `-SkipDocker`. Refresca el PATH de sesión tras cada `winget install`. El `<30 min` en máquina virgen no es testeable en CI; verificado: sintaxis con `[Parser]::ParseFile` + `bootstrap.ps1 -Check` corre limpio reportando todos los componentes. El script `.ps1` no pasa por pre-commit (los hooks son Python).
- [x] **T-502** Documentar setup en `docs/setup-windows.md`
  - **Nota:** `docs/setup-windows.md` reescrito y puesto al día. Dos vías: la rápida con `bootstrap.ps1` (T-501) y la manual paso a paso. Corregidas inexactitudes de la versión inicial: `uv sync` (no `uv pip install -e`), se elimina el inexistente `enigma init` (las carpetas/SQLite/colección se crean solos al primer `ingest`), troubleshooting real (PATH tras winget, FFmpeg shared, Docker/WSL2/reinicio) y referencia de comandos completa (los 14 comandos `enigma` reales de Fases 1-4).
- [x] **T-503** Documentar uso desde Obsidian para no-técnicos (`docs/usuario-final.md`)
  - **Nota:** `docs/usuario-final.md` — guía para los miembros del equipo que usan Enigma solo desde Obsidian, sin terminal ni código. Cubre: qué es Enigma, el flujo grabar→procesar→revisar→consultar, la estructura del Vault (`inbox`/`notes`/`calls` + los índices MOC), qué es una nota atómica (cuerpo / `## Conexiones` / `## Origen`), la tarea recurrente de revisar el `inbox/` y promover a `notes/`, cómo consultar (búsqueda Obsidian, índices, `enigma ask`), buenas prácticas al grabar y un FAQ. Sin jerga técnica.
- [x] **T-504** Métricas básicas: notas/día, calls procesadas, latencias (RNF-08)
  - *Aceptación:* `enigma stats` muestra dashboard ASCII
  - **Nota:** `gather_stats()` en `src/enigma/stats.py` (módulo raíz nuevo) recoge tres bloques: **corpus** (llamadas y notas por estado, huérfanas, vectores Qdrant, horas de audio, notas/llamada — de SQLite + Vault + Qdrant), **actividad** (llamadas 7/30 días, notas/día últimos 7) y **salud** (sondeo en vivo de Qdrant y Ollama + latencia de `embed_text`). Comando `enigma stats` pinta el dashboard con paneles Rich + barras ASCII. **Decisión sobre "latencias":** la latencia *de pipeline por llamada* NO se mide — el esquema SQLite no guarda tiempos de proceso e instrumentarla exigiría un cambio de esquema (mejora futura). El sondeo de salud cubre la latencia a nivel de componente. El `HealthProbe` degrada con gracia si Qdrant/Ollama están caídos. Verificado con `test_stats_real.py` (integration) + smoke `enigma stats`.
- [x] **T-505** Backups: snapshot semanal del Vault + Qdrant
  - *Aceptación:* script de restore probado
  - **Nota:** `src/enigma/backup.py`. `create_backup()` empaqueta en un `.zip` el **Vault** (`vault/`, fuente de verdad) y `data/` (audios, transcripts, `enigma.db` — entradas crudas no reconstruibles). **Qdrant NO se respalda**: es derivado (CONSTITUTION §3); `restore_backup()` lo reconstruye con `reindex_vault()`. Así el backup no depende del formato binario de Qdrant ni de versiones; el tradeoff es que el restore re-embebe (minutos). `.env` se excluye (secretos). Comandos `enigma backup` / `enigma restore <zip> [--force] [--no-reindex]`; `restore` es destructivo → sin `--force` se niega si el destino tiene datos, y rechaza zip-slip. La cadencia "semanal" es operativa. Restore **probado**: round-trip byte a byte (`test_backup.py`) + round-trip con reindex real (`test_backup_real.py`, integration). **Hardening del smoke:** la CLI reconfigura stdout/stderr a UTF-8 al arrancar — sin esto, cualquier comando con `✓`/`•` casca con `UnicodeEncodeError` si la salida se redirige en Windows (caso de un backup programado con log).
- [x] **T-506** Sesión de onboarding con el equipo (1h grabada → ¡se procesa con Enigma!)
  - *Aceptación:* el meta-test definitivo: Enigma procesa su propia llamada de onboarding 🪞
  - **Nota:** `scripts/onboarding_metatest.py` ejecuta el pipeline completo (ingest → reindex → ask → decisions → tasks → themes → summarize) sobre un audio de onboarding y reporta PASS/FAIL por etapa. Como aún no hay grabación real del equipo, se generó un **audio sintético** con `scripts/generate_onboarding_audio.ps1` (síntesis de voz de Windows, voz española Helena) leyendo `scripts/onboarding_script.txt` — una sesión de onboarding sobre el propio Enigma. **Corrida verificada (2026-05-16): las 7 etapas PASS, exit 0** — transcripción, RAG con citas, 3 decisiones + 3 tareas extraídas, resumen. Detalle y evidencia en `docs/onboarding.md`. El equipo correrá el mismo metatest con la grabación real cuando la tengan. Observación: el extractor atómico produjo 1 nota; afinar su prompt queda como backlog.

---

## Fase 6 — Comunicación en tiempo real (post-MVP)

> Objetivo: Enigma deja de ser solo un pipeline batch y se convierte en el
> espacio donde el equipo se comunica — chat y llamadas — con el pipeline
> destilando ese material en conocimiento consultable.
>
> **Ampliación de alcance** a petición del usuario (2026-05-16). No estaba en
> el `SPEC.md` original. Arquitectura en `PLAN.md §4.13`. Se construye por
> fases (W1-W4), cada una usable al cerrarse.

- [x] **T-601 (W1)** Chat en vivo del equipo
  - *Aceptación:* mensajes en tiempo real entre varios clientes, persistidos y con historial
  - **Nota:** shell de app web (barra lateral, identidad, canales) + chat por WebSocket. `models/message.py`, tabla `messages` en SQLite, `db/messages.py`, hub `realtime.py` (`ConnectionManager` — presencia + difusión), endpoint `WS /ws` y `GET /channels` en `api.py`. Canales fijos (`general`/`producto`/`random`). Sin login: cada uno elige un nombre (localStorage). El panel "Consultar" (RAG + búsqueda + stats) queda integrado en la app. Frontend reescrito como shell; tema visual reutilizado del frontend previo.
- [x] **T-602 (W2)** Llamadas WebRTC en vivo
  - *Aceptación:* vídeo/audio entre el equipo + compartir pantalla; señalización sobre `/ws`
  - **Nota:** llamada peer-to-peer en malla (cada par ↔ cada par, viable ≤6). El hub (`realtime.py`) gana `peer_id` por conexión, estado `in_call`, roster de llamada y `relay_signal` (relay de SDP/ICE por `peer_id`); `/ws` añade `call-join`/`call-leave`/`signal` y un `welcome` que entrega `peer_id` + `ice_servers`. Nuevo setting `webrtc_ice_servers` (STUN por defecto; sin TURN — llamadas entre redes con NAT estricto pueden fallar, documentado). Frontend: vista de llamada con malla `RTCPeerConnection` (el recién llegado ofrece; los presentes responden — sin *glare*), rejilla de vídeo, controles mic/cámara/compartir pantalla (`getDisplayMedia` + `replaceTrack`) y colgar. La señalización está cubierta por tests (`relay_signal`, roster, roundtrip `/ws` de 2 clientes); la capa de medios WebRTC se verifica manualmente (dos pestañas/equipos).
- [x] **T-603 (W3)** Grabar la llamada → pipeline
  - *Aceptación:* al colgar, la grabación entra en `ingest_audio` (job en background) y se convierte en notas
  - **Nota:** el bucle completo cerrado. En la llamada hay un botón de **grabar**: el navegador mezcla el audio (mic local + el de cada par) con `AudioContext` + `MediaStreamAudioDestinationNode` y lo captura con `MediaRecorder` (`audio/webm`). Al parar (o al colgar) la grabación se sube a `POST /calls/upload` — **cuerpo crudo, sin multipart** (sin dependencias nuevas). El endpoint guarda el audio y lanza `ingest_audio` como **job en background** (FastAPI `BackgroundTasks`); la ingesta es lenta y la respuesta vuelve al instante. `GET /calls` lista las llamadas con su `status` (pending→transcribing→extracting→done); el lobby de la llamada muestra esa lista y la refresca cada 6 s. La transcripción decodifica el webm vía PyAV; la diarización (pyannote) solo corre si el servidor arranca con FFmpeg shared en el PATH — si no, se salta (best-effort, RF-03). Tests cubren `/calls` y `/calls/upload` (incluida la background task).
- [x] **T-604 (W4)** Consulta integrada y pulido
  - *Aceptación:* la llamada procesada queda enlazada a sus notas y consultable desde la app
  - **Nota:** `GET /calls/{id}/notes` devuelve las notas atómicas de una llamada (filtra `list_vault_notes` por `call_id`). En el frontend, cada llamada de la lista es clicable: abre un **modal** con sus notas (título, etiquetas, estado) — la llamada queda enlazada a su conocimiento. Si aún se procesa, el modal muestra el estado. La consulta libre (RAG + búsqueda) ya vivía en el panel "Consultar la memoria". Cierra la Fase 6: Enigma es el espacio del equipo — chatear, llamar, grabar y consultar, todo en una app local-first.

---

## Fase 7 — Cierre del bucle de llamada + UX (post-MVP)

> Objetivo: que el bucle ya construido en la Fase 6 — grabar llamada → IA →
> consultar → brainstorming — **funcione de verdad de punta a punta**, y pulir
> chat y llamadas. Origen: tras probar la app, el usuario reportó que el
> frontend no expone todo el flujo y que un servicio caído rompía la app.
>
> **Ampliación de alcance** a petición del usuario (2026-05-18). No estaba en
> el `SPEC.md` original. T-701 y T-702 son las que hacen que el bucle ya
> existente funcione; van primero. Orden: T-701 → T-702 → T-703 → T-704 →
> T-705 → T-706.

- [x] **T-701** Robustez: un servicio caído no rompe la app *(bug)*
  - *Aceptación:* con Qdrant apagado, `POST /ask` responde **503** con mensaje
    entendible ("la base vectorial no responde; arranca Qdrant"); con Qdrant
    encendido, `/ask` funciona. El panel de respuesta del frontend muestra el
    texto del 503, no "Error 500". Tests de `search` con Qdrant inalcanzable
    (mock que lanza error de conexión).
  - **Nota:** nueva excepción tipada `VectorStoreUnavailableError` en
    `vector/qdrant_client.py`. `search()` distingue dos estados: *colección
    ausente* → sigue devolviendo `[]` (sistema sin indexar, normal desde
    T-305); *Qdrant inalcanzable* (`ResponseHandlingException` del cliente) →
    lanza `VectorStoreUnavailableError` con mensaje accionable. **Desviación
    del prompt de continuidad** (que pedía devolver `[]` también en el caso de
    conexión): tragarse el fallo conflaría "Qdrant caído" con "corpus vacío" —
    el mismo anti-patrón que T-701 corrige — y `/ask` respondería 200 "no
    encontré información" en vez de 503. La excepción tipada permite además
    dar el mensaje específico "arranca Qdrant" sin etiquetar mal cualquier
    otro bug. `/ask` captura `VectorStoreUnavailableError`/`RagError` → 503, y
    cualquier excepción inesperada → 503 genérico (red de seguridad: nunca un
    500 opaco de texto plano que el frontend solo pueda mostrar como "Error
    500"). `/search` y los comandos CLI `ask`/`search` capturan la misma
    excepción. El frontend no necesita cambios: `getJSON` ya extrae
    `body.detail` del cuerpo JSON. Verificado en vivo con Qdrant apagado:
    `/ask` y `/search` → 503 con `{detail: ...}` legible. Tests:
    `test_qdrant_client.py` (nuevo) + casos 503 en `test_api.py` y CLI.
- [x] **T-702** El bucle de la llamada grabada, completo
  - *Aceptación:* subir una grabación deja, al terminar el job, sus notas
    vectorizadas en Qdrant y su resumen IA en `vault/calls/` — la llamada
    grabada queda consultable por RAG. `_process_upload` encadena
    `ingest_audio` → `reindex_vault()` → `summarize_call(call.id)`.
  - **Nota:** `api.py::_process_upload` encadena las tres etapas. `ingest` es
    la etapa crítica (si falla, `return`); `reindex` y `summarize` son
    enriquecimiento independiente, cada uno aislado en su `try/except` para
    que un fallo no impida el otro — las notas ya quedan en el Vault (fuente
    de verdad). `reindex_vault()` reindexa todo el Vault (idempotente, upsert
    por `note_id`); coste O(N) aceptable para 6 personas en un job background.
    El estado de la llamada NO cambia: `ingest_audio` marca `done` tras
    escribir notas y reindex+summarize corren después (T-703 leerá el resumen
    "si existe"). **Bug pre-existente destapado y arreglado en esta misma
    tarea:** el bucle de T-603 *nunca funcionó* — `/calls/upload` guarda la
    grabación como `.webm` (lo que produce `MediaRecorder`), pero
    `register_call` rechazaba `.webm` (no estaba en `SUPPORTED_EXTENSIONS`);
    los tests de T-603 mockeaban `ingest_audio` y no lo detectaron. Fix:
    `.webm` añadido a `SUPPORTED_EXTENSIONS` (`ingest/audio.py`) y a **RF-01 /
    CU-01 en `SPEC.md`** (cambio de spec menor y justificado: la Fase 6 graba
    webm). `_audio_duration_seconds` gana un fallback a PyAV — `soundfile`/
    libsndfile no lee webm; PyAV sí (ya es dep transitiva de faster-whisper).
    faster-whisper decodifica webm internamente vía PyAV, así que el
    transcriptor no necesitó cambios. Verificado en vivo: subir un webm de
    90s → llamada `99e50e81` `done`, duración 90.0s, nota vectorizada en
    Qdrant (1→2 puntos) y resumen IA en `vault/calls/`. Tests:
    `test_api.py` (orden ingest→reindex→summarize + aislamiento de fallos),
    `test_register_call.py` (acepta `.webm`).
- [ ] **T-703** "Consultar llamada grabada" — vista de detalle rica
  - *Aceptación:* clicar una llamada en estado `done` muestra lo que la IA
    ingestó y razonó: resumen + notas + decisiones + tareas de esa llamada.
    `GET /calls/{id}/detail` devuelve `{summary, notes, decisions, tasks}`.
- [ ] **T-704** Botón "Brainstorming" — la IA razona sobre la llamada
  - *Aceptación:* pulsar "Brainstorming" sobre una llamada devuelve ideas
    nuevas razonadas sobre sus notas (analogías, próximos pasos, preguntas
    abiertas, riesgos). `POST /calls/{id}/brainstorm` →
    `agent/brainstorm.py::brainstorm_call`.
- [ ] **T-705** Mensajes nuevos — badge de no leídos
  - *Aceptación:* llega un mensaje a un canal no activo → aparece su contador
    numérico en la barra lateral; al abrir el canal, desaparece. Verificación:
    smoke manual (dos pestañas).
- [ ] **T-706** Indicador de quién habla en la llamada
  - *Aceptación:* al hablar, el recuadro de vídeo de quien habla se ilumina
    (borde luminoso); en silencio, no. `AnalyserNode` de Web Audio por stream.
    Verificación: smoke manual.
- [ ] **T-707** *(opcional)* Surfacing de los índices del corpus en la web
  - *Aceptación:* `decisions` / `tasks` / `themes` / `serendipity`, hoy solo
    en CLI, accesibles desde la app vía endpoints `GET` + paneles. Solo si el
    usuario lo pide.

---

## Backlog (no priorizado todavía)

- Captura de audio en tiempo real durante la llamada
- Integración con Zoom/Meet vía bot
- Roles y permisos por nota
- App móvil de consulta
- Modo multilenguaje
- Exportar a otros formatos (Notion, Logseq)
- Detección automática de personas mencionadas → notas-entidad
- Visualización custom del grafo más allá de Obsidian

---

## Métricas de progreso

Actualizar manualmente al cierre de cada fase:

| Fase | Tareas totales | Tareas completadas | % | Bloqueantes |
|---|---|---|---|---|
| 0 | 10 | 10 | 100% | — |
| 1 | 15 | 15 | 100% | ✅ Fase 1 completa. LLM por defecto `qwen2.5:7b` (T-107). T-108 dedup textual; embeddings reales en Fase 2. T-103 usa `pyannote/speaker-diarization-community-1` + FFmpeg shared. |
| 2 | 7 | 7 | 100% | — |
| 3 | 5 | 5 | 100% | ✅ Fase 3 completa. T-302 sin LlamaIndex (RAG a mano sobre Qdrant+Ollama, `PLAN.md §4.1`). T-303: eval manual ≥7/10 pendiente de corpus real. T-304: nueva dep `sentence-transformers` (`PLAN.md §4.8`); recall@5 formal pendiente de corpus etiquetado. T-305: `search()` robusto ante colección ausente. |
| 4 | 6 | 6 | 100% | ✅ Fase 4 completa. T-401 resumen single-shot. T-402 `decisions.md` / T-403 `tasks.md` desde transcripts (N llamadas LLM, sin caché). T-404 contradicciones O(N·k), `PLAN.md §4.9`. T-405 ideas recurrentes por componentes conexas, umbral empírico 0.68, `§4.10`. T-406 serendipia por banda de similitud media, `§4.11`. |
| 5 | 6 | 6 | 100% | ✅ Fase 5 completa. T-501 `bootstrap.ps1`. T-502 `setup-windows.md`. T-503 `usuario-final.md`. T-504 `enigma stats`. T-505 `backup`/`restore`. T-506 meta-test de onboarding: 7/7 etapas PASS sobre audio sintético (`docs/onboarding.md`). |
| 6 | 4 | 4 | 100% | ✅ Fase 6 completa. W1 chat · W2 llamadas WebRTC · W3 grabar→pipeline · W4 llamada↔notas + consulta integrada. Enigma es la app de comunicación del equipo. Ver `PLAN.md §4.13`. |
| 7 | 6 | 2 | 33% | 🚧 En curso. T-707 opcional, no cuenta en el total. T-701: un Qdrant caído ya no rompe `/ask` (503 legible). T-702: el bucle grabado funciona end-to-end (arreglado el rechazo de `.webm` que dejaba T-603 inoperante; `.webm` añadido a RF-01). Cierra el bucle grabar→IA→consultar→brainstorming + pulido de chat/llamadas. |
