# Feature 001 — MVP Core: Audio → Notas atómicas

> **Estado:** Borrador · **Owner:** TBD · **Fase:** 1 (semanas 2-4)
> **Cubre:** RF-01, RF-02, RF-03, RF-04, RF-05, RF-10, RF-13

---

## Resumen ejecutivo

End-to-end mínimo: el usuario ejecuta `enigma ingest audio.m4a` y obtiene notas atómicas en Markdown dentro del Vault de Obsidian, **sin** wikilinks automáticos, **sin** búsqueda semántica. Ese es el alcance de v0.1.

## Historia de usuario

> Como Manuel (admin), quiero subir el audio de una llamada de equipo y obtener entre 5 y 30 notas atómicas en mi Vault de Obsidian, cada una con su origen rastreable hasta el segundo exacto de la grabación, para que ni una idea se me escape.

## Criterios de aceptación

- [ ] El comando `enigma ingest <path>` acepta `.wav`, `.mp3`, `.m4a`, `.ogg` (RF-01).
- [ ] Crea un registro `Call` en SQLite con `status=pending`.
- [ ] Lanza transcripción con faster-whisper y persiste `Transcript` JSON (RF-02).
- [ ] Diariza si hay ≥ 2 hablantes (RF-03).
- [ ] Llama al LLM (Ollama/Llama 3.1 8B) y obtiene notas atómicas (RF-04).
- [ ] Escribe cada nota como `.md` en `vault/inbox/` con frontmatter válido (RF-05).
- [ ] Crea nota índice de la llamada en `vault/calls/`.
- [ ] Reingerir el mismo audio NO duplica notas (RF-10).
- [ ] Actualiza `Call.status` a `done` al terminar.

## Out of scope (intencional)

- ❌ Wikilinks automáticos entre notas (Fase 2)
- ❌ Vectorización en Qdrant (Fase 2)
- ❌ Búsqueda semántica (Fase 3)
- ❌ Agente RAG (Fase 4)

## Diseño de interacción

```bash
$ enigma ingest C:\audios\brainstorm-padel.m4a --title "Brainstorm captación padel"

[1/4] Registrando llamada........................ ✓ call_id=3b9f7a2c
[2/4] Transcribiendo (faster-whisper large-v3)... ✓ 47:12 → 4823 palabras
[3/4] Diarizando (pyannote.audio)................ ✓ 3 hablantes
[4/4] Extrayendo notas atómicas (qwen2.5:7b).... ✓ 18 notas

Notas creadas en C:\Users\manul\Enigma_V3\vault\inbox\
Nota índice: vault/calls/2026-05-14-brainstorm-captacion-padel.md
```

## Componentes implicados

- `enigma.cli` — comando `ingest`
- `enigma.ingest.audio` — registro de Call
- `enigma.ingest.transcriber` — wrapper faster-whisper + pyannote
- `enigma.extract.extractor` — LLM call y chunking
- `enigma.extract.prompts` — plantilla de extracción
- `enigma.vault.writer` — escritura de `.md`
- `enigma.vault.frontmatter` — generación de YAML

## Prompt de extracción (v1)

```
Eres un asistente que convierte transcripciones de llamadas en notas atómicas estilo Zettelkasten.

REGLAS:
1. Una nota = una sola idea.
2. Cuerpo de 1-3 párrafos, máximo 200 palabras.
3. Título conciso, descriptivo, < 80 caracteres.
4. NO incluyas relleno conversacional ("creo que", "pues entonces").
5. Mantén el contenido factual; si es opinión, indícalo.
6. Devuelve JSON válido con la lista de notas.

FORMATO:
[
  {
    "title": "...",
    "body": "...",
    "tags": ["tag1", "tag2"],
    "timestamp_start": 412.5,
    "timestamp_end": 478.2,
    "speakers": ["SPEAKER_00"]
  }
]

TRANSCRIPCIÓN:
{transcript_chunk}
```

## Métricas para validar el feature

| Métrica | Objetivo |
|---|---|
| Notas extraídas por hora de audio | 5-30 |
| Notas válidas (JSON parseable) | ≥ 95% |
| Latencia procesamiento (audio 30 min, CPU 16GB) | ≤ 45 min |
| Tests pasando | 100% |
| Cobertura código nuevo | ≥ 70% |

## Tests obligatorios

1. **Unit**
   - `test_transcriber.py`: transcribe audio fixture en < 30s
   - `test_extractor.py`: parsea respuesta LLM y valida con Pydantic
   - `test_chunker.py`: divide transcript con overlap correcto
   - `test_writer.py`: idempotencia (escribir 2 veces produce el mismo fichero)
   - `test_frontmatter.py`: YAML válido y campos obligatorios

2. **Integration** (marker `@pytest.mark.integration`)
   - `test_pipeline_e2e.py`: audio fixture de 30s → ≥ 1 nota en vault/inbox

## Riesgos

- **Whisper carga lenta en primer uso:** modelo de 1.5GB. Mitigación: pre-descargar en bootstrap.
- **JSON malformado del LLM:** Llama 3 a veces inventa campos. Mitigación: usar `format: json` de Ollama y reintentar hasta 3 veces.
- **Audios largos saturan VRAM:** chunking en bloques de 30 min para faster-whisper.

## Tareas vinculadas

Ver `TASKS.md` → Fase 1, T-101 a T-115.
