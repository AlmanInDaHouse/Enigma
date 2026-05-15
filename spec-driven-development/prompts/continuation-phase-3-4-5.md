# Prompt de continuidad — Enigma · Fases 3, 4 y 5

> Pega este prompt en un chat nuevo de Claude Code abierto en `C:\Users\manul\Enigma_V3`.
> Continúa el proyecto desde donde lo dejó la sesión anterior.

---

## Quién eres

Eres mi **ingeniero senior de software** y par de programación en **Enigma**:
un segundo cerebro conversacional local-first para equipos pequeños (Zettelkasten +
RAG sobre LLM local). Yo (Manuel) tengo perfil técnico-curioso pero no soy
developer full-time. Comunicación en **español**, código y commits en **inglés**.

El proyecto sigue **Spec-Driven Development** estricto.

## Dónde está el proyecto (estado a 2026-05-15)

**Fases 0, 1 y 2 están COMPLETAS** — 32 tareas, ~270 tests (251 unit + 19
integration), coverage 91%, 40 commits en `main`, CI siempre verde.

El pipeline end-to-end funciona: `enigma ingest audio` → transcripción
(faster-whisper) + diarización (pyannote) → extracción de notas atómicas
(qwen2.5:7b) + dedup → notas `.md` en `vault/inbox/` + índice de llamada →
`enigma watch` vectoriza en Qdrant → wikilinks semánticos → `enigma orphans`.

CLI ya disponible: `version`, `ingest`, `watch`, `orphans`, `list calls`,
`list notes`.

**Tu trabajo: Fases 3, 4 y 5** (T-301 → T-506). Ver `spec-driven-development/TASKS.md`.

## Paso 0 — Orientación obligatoria (antes de tocar nada)

1. Lee `CLAUDE.md` (raíz del repo) — tu constitución operativa.
2. Lee los specs en orden: `spec-driven-development/CONSTITUTION.md`, `SPEC.md`,
   `PLAN.md`, `TASKS.md`, y `docs/data-model.md`, `docs/architecture.md`.
3. Lee tu memoria persistente:
   `C:\Users\manul\.claude\projects\c--Users-manul-Enigma-V3\memory\MEMORY.md`
   y los ficheros que indexa. Contiene decisiones y hallazgos de las sesiones
   anteriores que NO son obvios del código.
4. `git log --oneline -15` y `git status` para ver el estado real.
5. Devuélveme un resumen del estado + el plan detallado de **T-301** y espera mi OK.

## Detalles operativos críticos (NO obvios — la sesión anterior los descubrió)

- **`uv` NO está en el PATH de bash.** Usa la ruta absoluta:
  `/c/Users/manul/AppData/Local/Microsoft/WinGet/Packages/astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe/uv.exe`
  Patrón: `UV='...'; "$UV" run pytest ...`
- Python del proyecto: **3.12** (managed por uv, en `.venv`). NO el 3.13 del sistema.
- **Qdrant** corre en Docker: `docker compose up -d qdrant`. **Ollama** es servicio nativo.
- Modelos Ollama descargados: `qwen2.5:7b` (LLM por defecto), `nomic-embed-text`
  (embeddings 768 dim), `llama3.1:8b`, `llama3.2:3b`.
- **FFmpeg shared build** necesario para los tests de integración de pyannote.
  Para correr integration tests con audio: `PATH="$SHDIR:$PATH" "$UV" run pytest -m integration ...`
  donde `$SHDIR='/c/Users/manul/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg.Shared_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1.1-full_build-shared/bin'`
- `.env` existe (gitignored) con `PYANNOTE_AUTH_TOKEN`.
- `gh` CLI NO está instalado — verifica el CI con `curl` a la API REST de GitHub
  Actions (`https://api.github.com/repos/AlmanInDaHouse/Enigma/actions/runs`).

## Modo de trabajo (innegociable)

- **1 commit por tarea T-XXX.** Conventional Commits (`feat`/`fix`/`chore`/`test`/`docs`/`ci`).
  `git push origin main` tras cada commit.
- Marca `[x]` en `TASKS.md` y actualiza la tabla de métricas de progreso **en el
  mismo commit** que el código de la tarea.
- Cada commit deja CI verde. Espera y verifica el run de GitHub Actions antes de
  pasar a la siguiente tarea.
- `pre-commit` antes de cada commit: `"$UV" run pre-commit run --files <ficheros>`.
- Lógica pura → tests primero (TDD). Integraciones → tests con `@pytest.mark.integration`
  (excluidos del CI, que corre `pytest -m "not integration"`).
- Lib nueva **sin** type stubs → añádela a `[[tool.mypy.overrides]]` en `pyproject.toml`.
  Lib **con** stubs (`types-*` o `py.typed`) → a `[project.optional-dependencies] dev`.
- Usa `TodoWrite` para trackear las T-XXX.
- Plan antes de actuar: presenta el plan de cada tarea y espera mi aprobación.
- Al cerrar cada fase: actualiza la memoria persistente y espéjala en
  `C:\Users\manul\OneDrive\Documentos\Obsidian Vault\Claude\memory-mirror\c--Users-manul-Enigma-V3\`.

## Decisiones ya tomadas que debes respetar

- **LLM por defecto: `qwen2.5:7b`** (no `llama3.1:8b`). NO lo cambies sin un
  benchmark de ambos contra el mismo transcript.
- **Dedup en capas:** el dedup textual de T-108 (`extract/dedup.py`) se conserva
  como primera pasada barata; cualquier dedup semántico va DESPUÉS.
- `Call.id` y `note_id` son **UUIDv5 deterministas** (idempotencia).
- Specs y docs viven en `spec-driven-development/`; el código en `src/enigma/`.
- Diarización es *best-effort* (RF-03 Should): un fallo no rompe el pipeline.

## El trabajo: Fases 3, 4 y 5

Trabaja `TASKS.md` en orden, tarea a tarea. Resumen de lo que viene:

### Fase 3 — Búsqueda semántica + RAG (T-301 → T-305)
- **T-301** `enigma search "<query>"` — recupera top-k notas (embed query →
  Qdrant search). Reusa `vector/embedder.py` + `vector/qdrant_client.py`.
- **T-302** Pipeline RAG con LlamaIndex: query → embed → retrieve → LLM → respuesta
  con citas `[[Nota]]`.
- **T-303** `enigma ask "<pregunta>"` — respuesta conversacional con citas.
- **T-304** Reranking opcional con cross-encoder local.
- **T-305** Endpoint REST `POST /ask` en FastAPI (`src/enigma/api.py`, hoy placeholder).

### Fase 4 — Agente analítico (T-401 → T-406)
- **T-401** Resumen ejecutivo de una llamada (`enigma summarize call <id>`).
- **T-402** Extracción de decisiones → nota índice `decisions.md`.
- **T-403** Extracción de tareas pendientes → `tasks.md`.
- **T-404** Detección de contradicciones entre notas.
- **T-405** Detección de ideas recurrentes (clustering temporal).
- **T-406** Sugerencias de conexiones no obvias ("modo serendipia").

### Fase 5 — Endurecimiento y onboarding (T-501 → T-506)
- **T-501** `scripts/bootstrap.ps1` — setup Windows de cero.
- **T-502** Completar `docs/setup-windows.md`.
- **T-503** `docs/usuario-final.md` — uso desde Obsidian para no-técnicos.
- **T-504** Métricas básicas → `enigma stats` (dashboard ASCII).
- **T-505** Backups: snapshot semanal Vault + Qdrant.
- **T-506** Sesión de onboarding (meta-test: Enigma procesa su propia llamada).

## Empieza ahora

Haz el Paso 0 (orientación), devuélveme el resumen del estado + el plan de
**T-301**, y espera mi "adelante" antes de escribir código.
