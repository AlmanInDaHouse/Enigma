# Prompt de continuidad — Enigma · Fase 6 (hecha) y Fase 7 (por hacer)

> Documento de traspaso entre sesiones de Claude Code. Abre un chat nuevo en
> `C:\Users\manul\Enigma_V3` y continúa el proyecto desde aquí.
> Última actualización: 2026-05-16.

---

## Quién eres

Eres mi **ingeniero senior de software** y par de programación en **Enigma**.
Yo (Manuel) tengo perfil técnico-curioso pero no soy developer full-time.
Comunicación en **español**, código y commits en **inglés**. El proyecto sigue
**Spec-Driven Development** estricto.

---

## Estado del proyecto

**MVP completo (Fases 0-5, T-001..T-506)** — pipeline local-first: `enigma
ingest` audio → transcripción (faster-whisper) + diarización (pyannote) →
extracción de notas atómicas (qwen2.5:7b) → Vault Obsidian → Qdrant → RAG +
agente analítico (resúmenes, decisiones, tareas, contradicciones, ideas
recurrentes, serendipia) → CLI de 17 comandos. ~442 tests unit + ~43
integration, coverage > 90%, CI siempre verde.

**Fase 6 completa (T-601..T-604)** — ampliación post-MVP a petición mía:
Enigma es ahora también la **app de comunicación del equipo**, una web
servida por el mismo FastAPI. Se arranca con `enigma serve` y se abre en
**http://127.0.0.1:8077**.

- **T-601 (W1) chat en vivo** — `realtime.py` (hub WebSocket: presencia +
  difusión), tabla `messages`, `models/message.py`, `db/messages.py`,
  endpoint `WS /ws`. Canales fijos `general`/`producto`/`random`. Sin login:
  un nombre en `localStorage`.
- **T-602 (W2) llamadas WebRTC** — malla peer-to-peer (vídeo/audio/pantalla);
  el hub gana `peer_id` + relay de señalización; setting
  `webrtc_ice_servers` (STUN, sin TURN).
- **T-603 (W3) grabar → pipeline** — botón de grabar en la llamada: mezcla el
  audio (`AudioContext` + `MediaRecorder`) → `POST /calls/upload` (cuerpo
  crudo) → `ingest_audio` como job en background. `GET /calls` lista las
  llamadas con estado.
- **T-604 (W4) llamada ↔ notas** — `GET /calls/{id}/notes`; modal de detalle.

Frontend en `src/enigma/web/` (`index.html`, `style.css`, `app.js` vanilla —
sin npm, sin build). Construido con el skill oficial `frontend-design` de
Anthropic; estética "observatorio nocturno" (Fraunces + IBM Plex, fondo de
grafo de constelación). Arquitectura de la Fase 6 en `PLAN.md §4.13`.

**Último commit:** `2a4f807`. **Fase 7: por hacer** (este documento, §Fase 7).

---

## Detalles operativos críticos (NO obvios)

- **`uv` NO está en el PATH de bash.** Ruta absoluta:
  `/c/Users/manul/AppData/Local/Microsoft/WinGet/Packages/astral-sh.uv_Microsoft.Winget.Source_8wekyb3d8bbwe/uv.exe`
  Patrón: `UV='...'; "$UV" run pytest ...`
- Python del proyecto: **3.12** (managed por uv, en `.venv`).
- **Qdrant corre en Docker y DEBE estar arrancado:** `docker compose up -d
  qdrant`. Si está caído, `/ask` y `/search` fallan — fue la causa del
  "Error 500" que vio el usuario. Verificar: `curl http://localhost:6333/healthz`.
- **Ollama** es servicio nativo. Modelos: `qwen2.5:7b` (LLM por defecto),
  `nomic-embed-text` (embeddings 768d), `llama3.1:8b`, `llama3.2:3b`.
- **FFmpeg shared build** necesario para diarización (pyannote/torchcodec) y
  para los tests de integración de audio:
  `SHDIR='/c/Users/manul/AppData/Local/Microsoft/WinGet/Packages/Gyan.FFmpeg.Shared_Microsoft.Winget.Source_8wekyb3d8bbwe/ffmpeg-8.1.1-full_build-shared/bin'`
  `PATH="$SHDIR:$PATH" "$UV" run pytest -m integration ...`
- `gh` CLI NO instalado — verificar CI con `curl` a la API REST de GitHub
  Actions (`https://api.github.com/repos/AlmanInDaHouse/Enigma/actions/runs`).
- **La web:** `"$UV" run enigma serve` arranca uvicorn en el puerto 8077. Si
  el puerto está ocupado por un `serve` anterior, libéralo (matar el proceso
  que escucha en 8077) antes de relanzar. Tras cambiar `web/*.js|css`, el
  navegador necesita **recarga forzada** (Ctrl+Shift+R) por la caché.
- **Divergencia mypy:** pre-commit corre mypy en un entorno aislado; CI corre
  `uv run mypy src` en el venv. Una lib nueva en `src/` puede pasar uno y
  romper el otro. Ver memoria `feedback-mypy-overrides`.

---

## Modo de trabajo (innegociable)

- **1 commit por tarea T-XXX.** Conventional Commits (`feat`/`fix`/`chore`/
  `test`/`docs`/`ci`). `git push origin main` tras cada commit.
- Marca `[x]` en `TASKS.md` y actualiza la tabla de progreso en el mismo
  commit del código.
- Cada commit deja CI verde. Espera y verifica el run de GitHub Actions
  (vía `curl`) antes de la siguiente tarea.
- `pre-commit` antes de cada commit: `"$UV" run pre-commit run --files <...>`.
- Lógica pura → tests primero (TDD). Integraciones → `@pytest.mark.integration`
  (fuera del CI, que corre `pytest -m "not integration"`).
- Plan antes de actuar: presenta el plan de cada tarea y espera mi
  aprobación ("adelante" o equivalente).
- **Primer paso de esta fase:** añade la sección "Fase 7" a `TASKS.md` con las
  tareas de abajo (specs antes que código).
- Al cerrar la fase: actualiza la memoria persistente y espéjala en
  `C:\Users\manul\OneDrive\Documentos\Obsidian Vault\Claude\memory-mirror\c--Users-manul-Enigma-V3\`.

---

## Fase 7 — Integración del bucle de llamada + UX (por hacer)

> Origen: tras probar la app, el usuario reportó que el frontend no expone
> todo el flujo y pidió cerrar el bucle "grabar llamada → IA → consultar →
> brainstorming" y pulir el chat y las llamadas.

### T-701 · Robustez: un servicio caído no rompe la app *(bug)*
- `vector/qdrant_client.py::search` — envolver `collection_exists`/
  `query_points` en `try/except` de errores de conexión → devolver `[]`
  (hoy solo maneja "colección no existe", no "Qdrant no responde").
- `api.py` — `/ask` captura cualquier excepción no-`RagError` → HTTP 503 con
  mensaje claro ("la base vectorial no responde; arranca Qdrant").
- Frontend: el panel de respuesta muestra el texto del 503, no "Error 500".
- *Aceptación:* con Qdrant apagado, `/ask` responde 503 entendible; encendido,
  funciona. Tests de `search` con Qdrant inalcanzable (mock que lanza
  `ConnectionError`).

### T-702 · El bucle de la llamada grabada, completo
- Hoy `/calls/upload` → `ingest_audio` crea notas en el Vault **pero NO las
  vectoriza en Qdrant ni genera el resumen**. Sin eso la llamada grabada no es
  consultable por RAG.
- `api.py::_process_upload` debe encadenar: `ingest_audio` → `reindex_vault()`
  (vectoriza las notas nuevas en Qdrant) → `summarize_call(call.id)`.
- *Aceptación:* subir una grabación deja, al terminar, sus notas en Qdrant y su
  resumen en `vault/calls/`. **Nota honesta:** grabar "lo que dices" exige un
  micrófono; sin micro la grabación solo capta a los demás.

### T-703 · "Consultar llamada grabada" — vista de detalle rica
- `api.py` — `GET /calls/{id}/detail` → `{summary, notes, decisions, tasks}`
  (lee la nota-resumen `{índice}-summary.md` + filtra notas/decisiones/tareas
  por `call_id`).
- Frontend: el modal de llamada pasa a vista de detalle, con botón claro
  **"Consultar llamada grabada"**; muestra el resumen IA + notas + decisiones
  + tareas de esa llamada.
- *Aceptación:* clicar una llamada `listo` muestra lo que la IA ingestó y
  razonó de ella.

### T-704 · Botón "Brainstorming" — la IA razona sobre la llamada
- `agent/brainstorm.py` (nuevo) — `brainstorm_call(call_id) -> Brainstorm`;
  prompt en `agent/prompts.py` (expandir ideas: analogías, próximos pasos,
  preguntas abiertas, riesgos, sobre las notas de esa llamada).
- `api.py` — `POST /calls/{id}/brainstorm` → el razonamiento.
- Frontend: botón "Brainstorming" en el detalle de la llamada → muestra el
  resultado.
- *Aceptación:* pulsar "Brainstorming" sobre una llamada devuelve ideas nuevas
  razonadas sobre su contenido.

### T-705 · Mensajes nuevos — badge de no leídos
- Frontend (`app.js`): contador de no leídos por canal; un mensaje a un canal
  no activo lo incrementa; `setChannel` lo limpia. Badge numérico en cada
  ítem de canal de la barra lateral.
- *Aceptación:* llega un mensaje a un canal no activo → aparece su contador;
  al abrir el canal, desaparece. Verificación: smoke manual (dos pestañas).

### T-706 · Indicador de quién habla en la llamada
- Frontend (`app.js`): un `AnalyserNode` de Web Audio por stream (local +
  remotos); mide el nivel de audio; por encima de un umbral → clase
  `.speaking` en el tile de vídeo → borde luminoso (CSS en `style.css`).
- *Aceptación:* al hablar, el recuadro de quien habla se ilumina; en silencio,
  no. Verificación: smoke manual.

### T-707 (opcional) · Surfacing de los índices del corpus en la web
- Exponer en la web los índices transversales que hoy solo están en CLI:
  `decisions` / `tasks` / `themes` / `serendipity`. Endpoints `GET` que lean
  los `.md` del Vault o regeneren, + paneles en la app.
- Solo si el usuario lo pide.

**Orden recomendado:** T-701 → T-702 → T-703 → T-704 → T-705 → T-706.
T-701 y T-702 son las que hacen que el bucle ya construido *funcione de
verdad*; hazlas primero.

---

## Decisiones ya tomadas que debes respetar

- **Local-first.** Sin APIs externas en el flujo (STUN de WebRTC es la única
  excepción, configurable y vaciable).
- **RAG sin LlamaIndex** — retrieve+generate a mano sobre Qdrant+Ollama. No
  reintroducir LlamaIndex. Ver memoria `feedback-llamaindex-skip`.
- **LLM por defecto `qwen2.5:7b`** — no cambiar sin benchmark.
- **Frontend sin toolchain** — HTML/CSS/JS vanilla servido por FastAPI. Nada
  de npm/React/build.
- **Llamadas en malla** (no SFU), STUN sin TURN, sin login real — todo
  documentado en `PLAN.md §4.13`.
- Umbrales de embeddings se **miden**, no se adivinan (`nomic-embed-text`
  tiene suelo ~0.60). Ver memoria `feedback-embedding-thresholds`.
- CLI/scripts reconfiguran stdout a UTF-8 al arrancar (Windows cp1252).
- `Call.id` y `note_id` son UUIDv5 deterministas (idempotencia).

---

## Memoria persistente

Lee `C:\Users\manul\.claude\projects\c--Users-manul-Enigma-V3\memory\MEMORY.md`
y los ficheros que indexa — decisiones y hallazgos de sesiones anteriores que
NO son obvios del código.

## Documentos canónicos

`spec-driven-development/`: `CONSTITUTION.md`, `SPEC.md`, `PLAN.md` (la
arquitectura de la Fase 6 está en §4.13), `TASKS.md`, `docs/`.

---

## Empieza así

1. Lee `CLAUDE.md`, los specs canónicos, la memoria persistente y este
   documento.
2. `git log --oneline -15` y `git status`.
3. Comprueba que Qdrant y Ollama responden; si Qdrant está caído,
   `docker compose up -d qdrant`.
4. Añade la sección "Fase 7" a `TASKS.md` (T-701..T-706).
5. Devuélveme un resumen del estado + el plan detallado de **T-701** y espera
   mi "adelante".
