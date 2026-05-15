# Enigma — Setup en Windows

> Guía para levantar Enigma desde cero en una máquina Windows 10/11.
> Hay dos caminos: el **script `bootstrap.ps1`** (recomendado) o la
> **instalación manual** paso a paso.

---

## Requisitos

**Hardware recomendado:**

- CPU: 8 cores.
- RAM: 16 GB mínimo (32 GB cómodo — Whisper + LLM local).
- GPU: NVIDIA con ≥ 6 GB VRAM (opcional; acelera Whisper).
- Disco: ≥ 50 GB libres (modelos de Ollama ~5 GB, audios, Qdrant).

**Software** (lo instala `bootstrap.ps1`, salvo Git):

| Software | Para qué |
|---|---|
| Git | clonar el repo y sincronizar el Vault |
| winget | gestor de paquetes de Windows (viene con Windows 11) |
| uv | gestor de paquetes Python + entorno virtual |
| Python 3.12 | runtime (gestionado por uv) |
| FFmpeg **shared build** | `Gyan.FFmpeg.Shared` — obligatorio para diarización (`pyannote` carga audio vía `torchcodec`, que necesita las DLLs; el build *estático* NO sirve) y para `sentence-transformers` |
| Ollama | LLM (`qwen2.5:7b`) y embeddings (`nomic-embed-text`) locales |
| Docker Desktop | contenedor de Qdrant (base vectorial) |
| Obsidian | interfaz del Vault de notas |

---

## Vía rápida — `bootstrap.ps1`

**1. Instala Git** (si no lo tienes): https://git-scm.com/download/win

**2. Clona el repositorio:**

```powershell
cd C:\Users\<tu-usuario>
git clone https://github.com/AlmanInDaHouse/Enigma.git Enigma_V3
cd Enigma_V3
```

**3. Ejecuta el bootstrap:**

```powershell
# Verifica primero qué falta, sin instalar nada:
.\scripts\bootstrap.ps1 -Check

# Instalación completa:
.\scripts\bootstrap.ps1
```

El script instala uv, Python 3.12, las dependencias, FFmpeg, Ollama y sus
modelos (~5 GB), Docker Desktop, crea el `.env` y arranca Qdrant. Es
**idempotente**: si algo falla puedes reejecutarlo sin miedo.

> **Docker Desktop** puede pedir **reiniciar Windows** y activar WSL2. Tras
> reiniciar y arrancar Docker, **reejecuta `.\scripts\bootstrap.ps1`** para
> que levante Qdrant.
>
> Si gestionas Docker aparte: `.\scripts\bootstrap.ps1 -SkipDocker`.

**4. Reabre la terminal** para que el PATH recoja lo recién instalado.

**5. Rellena el token de HuggingFace** (solo si quieres diarización de
hablantes). Edita `.env` y pon tu token en `PYANNOTE_AUTH_TOKEN`; además
acepta las condiciones del modelo `pyannote/speaker-diarization-community-1`
en huggingface.co. Sin token, la transcripción funciona igual pero sin
distinguir hablantes (RF-03 es *best-effort*).

Salta al **Vault de Obsidian** más abajo.

---

## Vía manual

Por si prefieres control paso a paso o `bootstrap.ps1` falla en algún punto.

**1. Clona el repo** (igual que arriba).

**2. Instala las herramientas con winget:**

```powershell
winget install --exact --id astral-sh.uv
winget install --exact --id Gyan.FFmpeg.Shared
winget install --exact --id Ollama.Ollama
winget install --exact --id Docker.DockerDesktop
```

Reabre la terminal después (para refrescar el PATH).

**3. Python y dependencias** (desde la raíz del repo):

```powershell
uv python install 3.12
uv sync
```

`uv sync` crea `.venv` con Python 3.12 e instala todo desde `uv.lock`.

**4. Modelos de Ollama:**

```powershell
ollama pull qwen2.5:7b
ollama pull nomic-embed-text
```

Ollama corre como servicio en `http://localhost:11434`.

**5. Variables de entorno:**

```powershell
Copy-Item .env.example .env
notepad .env
```

Usa **forward slashes** en las rutas. Ajusta `ENIGMA_VAULT_PATH` y
`ENIGMA_DATA_PATH` a tu ruta del repo, y rellena `PYANNOTE_AUTH_TOKEN` si
quieres diarización.

**6. Arranca Qdrant** (con Docker Desktop en marcha):

```powershell
docker compose up -d qdrant
```

Verifica: `http://localhost:6333/dashboard` en el navegador.

> No hace falta inicializar la base SQLite ni la colección de Qdrant a mano:
> el primer `enigma ingest` crea las carpetas y la base de datos, y la
> colección `enigma_notes` se crea al vectorizar.

---

## Vault de Obsidian

El Vault es un **repositorio Git separado** del código, clonado dentro de
`vault/` (está en `.gitignore` del repo de código).

```powershell
# Repo dedicado para el Vault (créalo en GitHub si no existe):
git clone https://github.com/AlmanInDaHouse/Enigma-Vault.git vault
```

En Obsidian:

1. `Open folder as vault` → selecciona la carpeta `vault/` del repo.
2. `Settings → Community plugins → Browse` e instala **Obsidian Git**
   (y opcionalmente **Dataview** y **Templater**).
3. En Obsidian Git: *Auto pull on startup* ON, *Auto commit-and-push
   interval* 10 min.

Así el Vault se sincroniza solo entre los miembros del equipo.

---

## Smoke test

```powershell
# Procesa un audio en español de ≥ 30s:
uv run enigma ingest "C:\ruta\a\tu\audio.m4a"
```

Esperado: una nota índice en `vault/calls/`, varias notas atómicas en
`vault/inbox/`, y puntos nuevos en Qdrant (visibles en el dashboard).

```powershell
# Pregunta sobre el corpus:
uv run enigma ask "¿De qué se habló en la última llamada?"
```

---

## Troubleshooting

**`uv`, `ollama` o `ffmpeg` "no se reconoce" tras instalarlos**
→ Reabre la terminal: winget actualiza el PATH pero la sesión abierta no lo
ve. `bootstrap.ps1` refresca el PATH dentro de su propia ejecución.

**La diarización falla / no distingue hablantes**
→ Necesita FFmpeg **shared build** (`Gyan.FFmpeg.Shared`) en el PATH; el
build estático no sirve. Y `PYANNOTE_AUTH_TOKEN` relleno en `.env`. Sin
esto, la transcripción funciona igual pero sin hablantes.

**Qdrant no responde en `:6333`**
→ Comprueba que Docker Desktop está arrancado. `docker compose logs qdrant`.
Causa común: el puerto 6333 ya está ocupado.

**Docker Desktop pide reiniciar / WSL2**
→ Es normal en la primera instalación. Reinicia Windows, arranca Docker
Desktop y reejecuta `.\scripts\bootstrap.ps1`.

**Ollama no responde**
→ Reinicia el servicio (PowerShell como administrador):
`Get-Service Ollama | Restart-Service`.

**`faster-whisper` falla al cargar el modelo en GPU**
→ Verifica el driver NVIDIA y CUDA 12. Sin GPU, en `.env`: `WHISPER_DEVICE=cpu`.

**Conflicto de Git en el Vault**
→ En Obsidian: `Ctrl+P` → `Git: Pull`, resuelve el conflicto en el `.md` y
`Git: Commit and push`.

**El antivirus bloquea el file watcher (`enigma watch`)**
→ Excluye la carpeta del repo en Windows Defender.

---

## Referencia de comandos

```powershell
# Pipeline de ingesta
uv run enigma ingest <audio>        # audio → notas en el Vault
uv run enigma watch                 # re-vectoriza el Vault al detectar cambios

# Consulta
uv run enigma search "<consulta>"   # notas top-k por similitud semántica
uv run enigma ask "<pregunta>"      # respuesta RAG con citas
uv run enigma serve                 # API REST (POST /ask)

# Agente analítico (regeneran índices en el Vault)
uv run enigma summarize call <id>   # resumen ejecutivo de una llamada
uv run enigma decisions             # decisions.md — decisiones del corpus
uv run enigma tasks                 # tasks.md — tareas pendientes
uv run enigma contradictions        # contradictions.md — contradicciones
uv run enigma themes                # recurring-themes.md — ideas recurrentes
uv run enigma serendipity           # serendipity.md — conexiones no obvias

# Inspección
uv run enigma list calls            # llamadas registradas
uv run enigma list notes --last 7d  # notas recientes
uv run enigma orphans               # marca notas sin conexiones

# Reconstruir Qdrant desde el Vault (si se desincroniza)
uv run python scripts/reindex.py
```
