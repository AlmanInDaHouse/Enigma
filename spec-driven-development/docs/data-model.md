# Enigma — Modelo de Datos

> Detalla las tres entidades principales: `Call`, `Transcript`, `Note`. Más entidades auxiliares.

---

## 1. Call

Representa una llamada grabada que ingresa al sistema.

**Almacenamiento:** SQLite (tabla `calls`) + fichero de audio en `data/audio/{call_id}.{ext}`.

```python
class Call(BaseModel):
    id: UUID                      # UUIDv5(NAMESPACE, content_hash) — determinista por contenido
    content_hash: str             # SHA-256 hex (64 chars, lowercase) del fichero original
    title: str | None             # opcional, editable
    audio_path: Path              # ruta al fichero copiado (data/audio/{id}.{ext})
    duration_seconds: float
    language: str                 # ISO-639-1, p.ej. "es"
    recorded_at: datetime         # cuándo se grabó (mtime del fichero original)
    ingested_at: datetime         # cuándo entró a Enigma
    participants: list[str]       # nombres conocidos (manual o derivado)
    status: Literal["pending", "transcribing", "extracting", "done", "failed"]
    error: str | None
```

> **Idempotencia (RF-10).** `id` se deriva de `content_hash` mediante `uuid5(NAMESPACE, content_hash)`, por lo que reingerir el mismo fichero produce siempre el mismo `id` y permite *upsert* en SQLite usando `content_hash` como clave única alternativa.

### Esquema SQLite

```sql
CREATE TABLE calls (
    id            TEXT PRIMARY KEY,
    content_hash  TEXT NOT NULL UNIQUE,    -- SHA-256 hex; UNIQUE garantiza idempotencia
    title         TEXT,
    audio_path    TEXT NOT NULL,
    duration      REAL NOT NULL DEFAULT 0.0,
    language      TEXT NOT NULL DEFAULT 'es',
    recorded_at   TEXT NOT NULL,
    ingested_at   TEXT NOT NULL,
    participants  TEXT NOT NULL DEFAULT '[]',    -- JSON array de strings
    status        TEXT NOT NULL DEFAULT 'pending',
    error         TEXT
);

CREATE INDEX idx_calls_content_hash ON calls(content_hash);
```

---

## 2. Transcript

Salida del transcriptor + diarizador. Es un artefacto **derivado**: puede reconstruirse desde el audio.

**Almacenamiento:** JSON en `data/transcripts/{call_id}.json`.

```python
class TranscriptSegment(BaseModel):
    start: float                  # segundos
    end: float
    speaker: str | None           # "SPEAKER_00", "SPEAKER_01", o nombre si está mapeado
    text: str
    confidence: float | None      # 0-1

class Transcript(BaseModel):
    call_id: UUID
    model: str                    # p.ej. "faster-whisper:large-v3"
    diarization_model: str | None
    language: str
    segments: list[TranscriptSegment]
    created_at: datetime
```

---

## 3. Note (entidad central)

La nota atómica es el ciudadano de primera clase del sistema. **Vive en el Vault como Markdown**, no en una base de datos.

### Estructura del fichero `.md`

```markdown
---
id: 8f2a1c4e-1234-5678-9abc-def012345678
title: "Estrategia de captación para clubs de padel"
created_at: 2026-05-14T18:32:00+02:00
source:
  call_id: 3b9f7a2c-aaaa-bbbb-cccc-ddddeeeeffff
  timestamp_start: 412.5
  timestamp_end: 478.2
  speakers: ["Manuel"]
tags:
  - estrategia
  - captacion
  - padel
content_hash: 7a1f9b3e2d4c5a6b8e0d2c4f6a8b0d2e4f6a8b0d2e4f6a8b0d2e4f6a8b0d2e4f
status: validated         # one of: draft | validated | archived
extracted_by: llama3.1:8b
---

# Estrategia de captación para clubs de padel

Los clubs de padel representan un nicho de alta densidad y baja saturación competitiva en personalización deportiva. La estrategia parte de identificar clubs con > 100 socios activos y ofrecerles un paquete inicial de equipación con descuento por volumen.

El punto diferencial es la posibilidad de personalización individual dentro de un diseño base de club, lo que aumenta el ticket medio sin aumentar el coste operativo significativamente.

## Conexiones

- [[Padel - panorama del mercado en España]]
- [[Modelo de pricing por volumen]]
- [[Personalización individual dentro de equipación grupal]]

## Sugerencias

- [[Captación de clubs running]] *(similar approach, distinto deporte)*

## Origen

Mencionado en [[Call - 2026-05-14 brainstorm captacion]] entre los minutos 6:52 y 7:58.
```

### Campos obligatorios del frontmatter

| Campo | Tipo | Obligatorio | Descripción |
|---|---|---|---|
| `id` | UUIDv5 | sí | Determinista a partir de `call_id + chunk_id` |
| `title` | string | sí | Conciso, < 80 caracteres |
| `created_at` | ISO 8601 | sí | Momento de extracción |
| `source.call_id` | UUID | sí | Referencia a la llamada |
| `source.timestamp_start` | float | sí | Segundos desde inicio del audio |
| `source.timestamp_end` | float | sí | Segundos desde inicio del audio |
| `source.speakers` | list | sí | Hablantes (puede estar vacío si no se diarizó) |
| `tags` | list | sí | Mínimo 1 tag |
| `content_hash` | string | sí | SHA-256 del cuerpo (para detectar ediciones) |
| `status` | enum | sí | `draft` (inbox), `validated` (notes), `archived` |
| `extracted_by` | string | sí | Modelo usado, para trazabilidad |

### Reglas de validación

- `id` es UUIDv5 con namespace fijo + `call_id` + `chunk_id` → idempotente
- `content_hash` cambia si el cuerpo se edita → trigger de re-vectorización
- Una nota sin tags ni wikilinks va a `inbox/` con tag `#review-needed`
- Las notas en `notes/` deben tener al menos 1 wikilink

---

## 4. Entidades auxiliares (v2+)

### Person
Una nota especial en `vault/people/{slug}.md` que agrupa todo lo dicho por o sobre una persona.

### Topic / Concept
Una nota-entidad en `vault/topics/{slug}.md` que actúa como hub temático.

### Decision
Tipo especial de nota con frontmatter extendido:
```yaml
type: decision
decided_at: 2026-04-12
decided_by: ["Manuel", "Equipo"]
status: active | revisited | reversed
reverses: <id-of-previous-decision>  # si aplica
```

### Task
```yaml
type: task
assignee: "Manuel"
mentioned_at: 2026-05-14
due: 2026-05-20  # si se detecta
status: open | done
```

---

## 5. Esquema en Qdrant

**Colección:** `enigma_notes`

```python
{
    "vectors": {
        "size": 768,                      # nomic-embed-text
        "distance": "Cosine"
    },
    "payload_schema": {
        "note_id": "keyword",             # UUID
        "title": "text",
        "tags": "keyword[]",
        "call_id": "keyword",
        "created_at": "datetime",
        "speakers": "keyword[]",
        "status": "keyword",
        "content_hash": "keyword"
    }
}
```

Cada punto en Qdrant: `id = note_id`, payload con metadatos para filtrado, vector del cuerpo.

---

## 6. Diagrama de relaciones

```
Call (1) ──────────── (N) Note
  │                       │
  │ (1)                   │ (N)
  │                       │ (vector)
  ▼                       ▼
Transcript          Qdrant point
                          │
                          │ (semantic neighbors)
                          ▼
                    [[wikilinks]] → Note
```
