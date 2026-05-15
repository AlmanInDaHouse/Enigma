# Enigma — Setup en Windows

> Guía paso a paso para levantar Enigma desde cero en `C:\Users\manul\Enigma_V3`.

---

## Requisitos previos

| Software | Versión mínima | Cómo obtener |
|---|---|---|
| Windows | 10 / 11 | — |
| Python | 3.11+ | https://www.python.org/downloads/ (marcar "Add to PATH") |
| Git | 2.40+ | https://git-scm.com/download/win |
| Docker Desktop | 4.25+ | https://www.docker.com/products/docker-desktop |
| Ollama | 0.1.40+ | https://ollama.com/download/windows |
| Obsidian | 1.5+ | https://obsidian.md/download |
| ffmpeg | 6.0+ | https://www.gyan.dev/ffmpeg/builds/ (añadir a PATH) |
| uv (recomendado) | latest | `winget install astral-sh.uv` |

**Hardware recomendado:**
- CPU: 8 cores
- RAM: 16 GB mínimo (32 GB cómodo)
- GPU: NVIDIA con ≥ 6 GB VRAM (opcional pero acelera Whisper y Llama)
- Disco: ≥ 50 GB libres (modelos + audios + Qdrant)

---

## Paso 1 — Clonar repos

```powershell
cd C:\Users\manul
git clone https://github.com/AlmanInDaHouse/Enigma.git Enigma_V3
cd Enigma_V3
```

Para el Vault (repo separado):
```powershell
# crear un nuevo repo privado en GitHub: Enigma-Vault
git clone git@github.com:AlmanInDaHouse/Enigma-Vault.git vault
```

---

## Paso 2 — Instalar Ollama y descargar modelos

```powershell
# Tras instalar Ollama desde el .exe oficial:
ollama pull qwen2.5:7b          # LLM por defecto (ver PLAN.md §1)
ollama pull nomic-embed-text    # bloqueante T-006; embedder para Fase 2

# Verificar
ollama run qwen2.5:7b "Hola, ¿estás listo?"
```

Ollama queda corriendo como servicio Windows en `http://localhost:11434`.

---

## Paso 3 — Levantar Qdrant

Desde la raíz del repo:

```powershell
docker compose up -d qdrant
```

Verificar: abrir `http://localhost:6333/dashboard` en navegador.

---

## Paso 4 — Crear entorno Python e instalar dependencias

Con **uv** (recomendado, rapidísimo):

```powershell
uv venv
.venv\Scripts\Activate.ps1
uv pip install -e ".[dev]"
```

O con pip clásico:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

---

## Paso 5 — Configurar variables de entorno

Copiar plantilla:

```powershell
copy .env.example .env
notepad .env
```

Editar las rutas (importante en Windows usar **forward slashes** o doble backslash):

```env
ENIGMA_VAULT_PATH=C:/Users/manul/Enigma_V3/vault
ENIGMA_DATA_PATH=C:/Users/manul/Enigma_V3/data
```

---

## Paso 6 — Inicializar la base SQLite y carpetas

```powershell
enigma init
```

Crea:
- `data/audio/`
- `data/transcripts/`
- `data/enigma.db` (SQLite)
- Colección `enigma_notes` en Qdrant

---

## Paso 7 — Configurar Obsidian

1. Abrir Obsidian
2. `Open folder as vault` → seleccionar `C:\Users\manul\Enigma_V3\vault`
3. `Settings → Community plugins → Browse`
4. Instalar y activar:
   - **Obsidian Git**
   - **Dataview**
   - **Templater**
5. En Obsidian Git, configurar:
   - Auto pull on startup: ON
   - Auto commit and push interval: 10 min

---

## Paso 8 — Smoke test

```powershell
# audio de prueba (puede ser una nota de voz tuya de ≥ 30s en español)
enigma ingest "C:\Users\manul\Music\test.m4a"
```

Esperado:
- Aparece una nota en `vault/calls/`
- 5-30 notas en `vault/inbox/`
- Puntos nuevos en Qdrant (verlos en el dashboard)

```powershell
enigma ask "¿De qué se habló en la última llamada?"
```

---

## Troubleshooting

**`faster-whisper` falla al cargar modelo en GPU**
→ Verificar driver NVIDIA y CUDA 12. Si no tienes GPU, en `.env`: `WHISPER_DEVICE=cpu`.

**Ollama no responde**
→ Reiniciar el servicio: `Get-Service Ollama | Restart-Service` (PowerShell admin).

**Conflicto Git en el Vault**
→ En Obsidian: `Ctrl+P` → `Git: Pull` → resolver manualmente en VSCode → `Git: Commit and push`.

**Qdrant no arranca**
→ `docker compose logs qdrant`. Causa común: puerto 6333 ocupado.

**Antivirus bloquea el watcher**
→ Excluir `C:\Users\manul\Enigma_V3` de Windows Defender.

---

## Comandos útiles

```powershell
# estado del sistema
enigma status

# listar llamadas procesadas
enigma list calls

# reprocesar una llamada (idempotente)
enigma reprocess <call_id>

# reconstruir Qdrant desde el Vault (si se corrompe)
python scripts/reindex.py

# logs
Get-Content data\logs\enigma.log -Wait
```
