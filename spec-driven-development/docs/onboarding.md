# Enigma — Meta-test de onboarding (T-506)

> El cierre del proyecto: Enigma procesa una sesión de onboarding y se valida
> el sistema completo de extremo a extremo. 🪞

---

## Qué es

El **meta-test de onboarding** es la prueba definitiva de Enigma: meter por el
pipeline completo la grabación de una sesión de onboarding del equipo y
comprobar, etapa por etapa, que todo funciona sobre material real.

`scripts/onboarding_metatest.py` ejecuta y verifica la cadena entera:

```
ingest → reindex → ask (RAG) → decisions → tasks → themes → summarize
```

Reporta **PASS/FAIL por etapa** y sale con código 0 si las etapas críticas
(`ingest`, `reindex`, `ask`) pasan.

---

## Cómo ejecutarlo

### Con la grabación real del equipo

```powershell
uv run python scripts/onboarding_metatest.py "C:\ruta\a\onboarding.wav"
```

### Con un audio sintético (si aún no hay grabación)

`scripts/generate_onboarding_audio.ps1` lee `scripts/onboarding_script.txt`
con la síntesis de voz de Windows y produce un `.wav`:

```powershell
.\scripts\generate_onboarding_audio.ps1
uv run python scripts/onboarding_metatest.py
```

> Para que la transcripción funcione, FFmpeg **shared build** debe estar en el
> PATH (ver `setup-windows.md`).

---

## Resultado de la corrida sintética (2026-05-16)

Ejecutado sobre `onboarding_sintetico.wav` — la sesión de onboarding de Enigma
narrada por la voz española de Windows (`scripts/onboarding_script.txt`):

| Etapa | Resultado |
|---|---|
| 1. ingest — audio → notas | ✅ PASS — 1 nota + índice de llamada (transcripción `large-v3` en CPU) |
| 2. reindex — notas → Qdrant | ✅ PASS — vector indexado |
| 3. ask — RAG con citas | ✅ PASS — 3/3 preguntas respondidas, con citas `[[wikilink]]` que resuelven a notas reales |
| 4. decisions — `decisions.md` | ✅ PASS — **3 decisiones** extraídas (las 3 del guion) |
| 5. tasks — `tasks.md` | ✅ PASS — **3 tareas** extraídas (las 3 del guion) |
| 6. themes — ideas recurrentes | ✅ PASS — 0 temas (correcto: una sola llamada no puede ser recurrente) |
| 7. summarize — resumen de la llamada | ✅ PASS — resumen ejecutivo escrito en `vault/calls/` |

**`RESULTADO: OK`** — Enigma procesó su propia sesión de onboarding de extremo
a extremo.

### Observación

El extractor atómico produjo **1 nota** de la sesión, mientras que los agentes
de decisiones y tareas capturaron las **3 + 3** completas. No es un fallo del
pipeline: los agentes analíticos (T-402/T-403) trabajan sobre el *transcript*
directamente, no sobre las notas atómicas — el diseño en capas funcionó. Aun
así, una extracción atómica más rica sería deseable; afinar el prompt del
extractor (`extract/prompts.py`) queda como mejora de backlog.

---

## Qué valida cada etapa

- **ingest** — transcripción (faster-whisper) + extracción de notas + escritura
  en el Vault. Es el corazón del pipeline (Fase 1).
- **reindex** — vectorización en Qdrant (Fase 2): el Vault queda consultable.
- **ask** — el pipeline RAG (Fase 3) responde preguntas citando notas reales.
- **decisions / tasks / themes** — el agente analítico (Fase 4) destila el
  corpus en índices transversales.
- **summarize** — resumen ejecutivo de la llamada (Fase 4).

Si las siete etapas pasan, las cinco fases del proyecto funcionan juntas sobre
material real.
