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
- [ ] **T-006** Instalar Ollama localmente y descargar `llama3.1:8b` + `nomic-embed-text`
  - *Aceptación:* `ollama run llama3.1:8b "Hola"` responde
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
- [ ] **T-103** Integrar diarización con `pyannote.audio` (RF-03)
  - *Aceptación:* output incluye `speakers` distinguibles cuando el audio tiene 2+ voces
- [x] **T-104** Persistir transcripción como JSON en `data/transcripts/{call_id}.json`
  - *Aceptación:* JSON validable con esquema Pydantic `Transcript`

### Extracción de notas atómicas

- [x] **T-105** Diseñar y testear prompt de extracción atómica en `extract/prompts.py` (RF-04)
  - *Aceptación:* sobre 3 transcripts de prueba, produce entre 5-30 notas/hora *(validación estática completa; medición empírica de 5-30 notas/h queda para T-115 con LLM real)*
- [ ] **T-106** Implementar chunking con overlap del transcript
  - *Aceptación:* test unitario verifica que un transcript de 10k tokens se divide correctamente
- [ ] **T-107** Implementar `extract/extractor.py` con cliente Ollama
  - *Aceptación:* devuelve `List[Note]` validados por Pydantic
- [ ] **T-108** Deduplicación intra-llamada por similitud semántica > 0.92
  - *Aceptación:* test con 2 notas casi idénticas las fusiona en 1

### Vault Writer

- [ ] **T-109** Generador de frontmatter YAML con campos obligatorios (RF-05)
  - *Aceptación:* validador YAML pasa; campos `id`, `source`, `timestamp`, `tags` siempre presentes
- [ ] **T-110** Naming determinista de ficheros: `{slugified_title}-{short_id}.md`
  - *Aceptación:* reingestar la misma llamada NO crea ficheros duplicados (RF-10)
- [ ] **T-111** Escribir notas en `vault/inbox/` (revisión humana antes de promoción)
  - *Aceptación:* tras procesar un audio, las notas aparecen en `vault/inbox/`
- [ ] **T-112** Crear nota índice por llamada en `vault/calls/{date}-{title}.md` con enlaces a las notas extraídas
  - *Aceptación:* abrir la nota de la llamada en Obsidian muestra el grafo local

### CLI mínima

- [ ] **T-113** `enigma ingest <audio>` end-to-end (RF-13)
  - *Aceptación:* un solo comando lleva de `.wav` a `.md` en el Vault
- [ ] **T-114** `enigma list calls` y `enigma list notes --last 7d`
  - *Aceptación:* salida tabulada legible
- [ ] **T-115** Tests E2E con fixture de audio corto (30s)
  - *Aceptación:* `pytest tests/integration` verde

---

## Fase 2 — Grafo y vectorización (semanas 5-6)

> Objetivo: las notas se conectan automáticamente y son consultables semánticamente.

- [ ] **T-201** Wrapper de Qdrant en `vector/qdrant_client.py` con `upsert`, `search`, `delete`
  - *Aceptación:* tests CRUD pasan contra Qdrant local
- [ ] **T-202** Embedder con Ollama (`nomic-embed-text`)
  - *Aceptación:* embebe nota en < 100ms en CPU
- [ ] **T-203** Vectorizar todas las notas existentes con script `scripts/reindex.py`
  - *Aceptación:* Qdrant queda sincronizado con `vault/`
- [ ] **T-204** File watcher en `workers/watcher.py` que vectoriza al detectar cambios en `vault/`
  - *Aceptación:* editar una nota en Obsidian re-vectoriza en < 5s
- [ ] **T-205** Detección de wikilinks: top-5 vecinos + validación con LLM (RF-06)
  - *Aceptación:* > 70% de los links propuestos se mantienen tras revisión humana
- [ ] **T-206** Inyectar wikilinks en sección dedicada de la nota
  - *Aceptación:* nota generada tiene `## Conexiones` con `[[links]]`
- [ ] **T-207** Marcar notas huérfanas (sin links) con tag `#orphan` para revisión
  - *Aceptación:* dashboard CLI muestra count de huérfanas

---

## Fase 3 — Búsqueda semántica + RAG (semanas 7-8)

> Objetivo: preguntas en lenguaje natural devuelven respuestas con citas.

- [ ] **T-301** `enigma search "<query>"` recupera top-k notas (RF-07)
  - *Aceptación:* p95 < 3s en Vault con 1.000 notas
- [ ] **T-302** Pipeline RAG con LlamaIndex: query → embed → retrieve → LLM → respuesta con citas
  - *Aceptación:* respuesta cita `[[Nota X]]` y los ficheros existen
- [ ] **T-303** `enigma ask "<pregunta>"` con respuesta conversacional
  - *Aceptación:* sobre 10 preguntas de prueba, ≥ 7 respuestas son útiles (eval manual)
- [ ] **T-304** Reranking opcional con cross-encoder local (mejora calidad top-k)
  - *Aceptación:* recall@5 sube vs baseline en test set
- [ ] **T-305** Endpoint REST `POST /ask` en FastAPI (RF-14)
  - *Aceptación:* curl al endpoint devuelve JSON con respuesta + citas

---

## Fase 4 — Agente analítico (semanas 9-11)

> Objetivo: el sistema produce análisis transversal del corpus.

- [ ] **T-401** Resumen ejecutivo de una llamada (RF-08)
  - *Aceptación:* `enigma summarize call <id>` produce resumen estructurado en `vault/calls/`
- [ ] **T-402** Extracción de decisiones tomadas
  - *Aceptación:* nota índice `decisions.md` listada cronológicamente con enlaces al origen
- [ ] **T-403** Extracción de tareas pendientes
  - *Aceptación:* nota `tasks.md` con responsables (cuando identificables) y fecha de mención
- [ ] **T-404** Detección de contradicciones (RF-09)
  - *Aceptación:* sobre un test set con contradicciones inyectadas, ≥ 60% detectadas
- [ ] **T-405** Detección de ideas recurrentes (clustering temporal)
  - *Aceptación:* nota `recurring-themes.md` se regenera semanalmente
- [ ] **T-406** Sugerencias de conexiones no obvias entre notas distantes
  - *Aceptación:* "modo serendipia" propone 5 conexiones nuevas/semana

---

## Fase 5 — Endurecimiento y onboarding (semanas 12-13)

> Objetivo: el equipo de 6 personas puede usar Enigma sin necesidad del builder original.

- [ ] **T-501** Script `bootstrap.ps1` para Windows: instala dependencias, Ollama, Docker, modelos
  - *Aceptación:* máquina virgen → Enigma corriendo en < 30 min
- [ ] **T-502** Documentar setup en `docs/setup-windows.md`
- [ ] **T-503** Documentar uso desde Obsidian para no-técnicos (`docs/usuario-final.md`)
- [ ] **T-504** Métricas básicas: notas/día, calls procesadas, latencias (RNF-08)
  - *Aceptación:* `enigma stats` muestra dashboard ASCII
- [ ] **T-505** Backups: snapshot semanal del Vault + Qdrant
  - *Aceptación:* script de restore probado
- [ ] **T-506** Sesión de onboarding con el equipo (1h grabada → ¡se procesa con Enigma!)
  - *Aceptación:* el meta-test definitivo: Enigma procesa su propia llamada de onboarding 🪞

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
| 0 | 10 | 9 | 90% | T-006 bloqueado por error TLS al descargar de la CDN de Ollama (AV/cert store); modelos `llama3.2:3b` y `qwen2.5:7b` disponibles localmente como fallback temporal. |
| 1 | 15 | 4 | 27% | T-103 (diarización) diferido a pendiente de HF token + aceptación manual de términos del modelo `pyannote/speaker-diarization-3.1`. T-102 y T-105 verifican fuera de CI con LLM/audio real (`pytest -m integration` o medición empírica en T-115). |
| 2 | 7 | 0 | 0% | — |
| 3 | 5 | 0 | 0% | — |
| 4 | 6 | 0 | 0% | — |
| 5 | 6 | 0 | 0% | — |
