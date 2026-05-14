# Enigma — Constitución del Proyecto

> **Estado:** v1.0 · Inmutable salvo enmienda explícita por consenso del equipo.
> **Propósito:** definir los principios no negociables que guían cualquier decisión técnica o de producto en Enigma.

---

## Identidad

**Enigma** es un sistema de gestión de conocimiento conversacional para equipos pequeños (máximo 6 personas) que transforma cada llamada en notas atómicas conectadas, vectorizadas y consultables semánticamente. Inspirado en el método Zettelkasten, opera sobre un *Vault* de Obsidian como única fuente de verdad de las notas.

---

## Principios fundacionales

### 1. Local-first, siempre

Todo el procesamiento (transcripción, embeddings, LLM, búsqueda) ocurre en máquinas controladas por el equipo. Ningún dato sensible cruza a APIs de terceros. Cualquier propuesta que rompa este principio requiere enmienda explícita.

**Implicación práctica:** se prohíben dependencias hard de OpenAI, Anthropic, Gemini u otros LLMs cloud en el flujo principal. Se permiten *opcionalmente* como fallback configurable y desactivado por defecto.

### 2. Una idea = una nota (Zettelkasten atómico)

Cada nota representa **una sola idea**, autocontenida y referenciable. Si una idea necesita explicarse mediante otra, se enlaza con `[[wikilinks]]`, no se anida.

**Implicación práctica:** el extractor de IA está calibrado para producir notas atómicas, no resúmenes extensos. Si una nota supera ~200 palabras de cuerpo, debe dividirse.

### 3. Obsidian es la única fuente de verdad

El Vault de Markdown es **canónico**. La base de datos vectorial (Qdrant), los índices, los caches y cualquier estructura derivada se pueden destruir y reconstruir desde cero a partir del Vault sin pérdida de información.

**Implicación práctica:** prohibido almacenar contenido único en la vector DB. Todo lo que está en Qdrant es derivado.

### 4. Idempotencia y reproducibilidad

Cualquier pipeline debe poder reejecutarse sobre la misma entrada y producir el mismo resultado (o uno equivalente). Reprocesar una transcripción no debe duplicar notas ni romper enlaces.

**Implicación práctica:** cada nota lleva un `source_id` y un `content_hash`. La ingesta usa *upsert*, no *insert*.

### 5. Trazabilidad total

Cada nota debe poder rastrearse hasta su origen: qué llamada, qué timestamp, qué hablante, qué transcripción.

**Implicación práctica:** el frontmatter YAML de cada nota incluye `source`, `timestamp`, `speakers` y `call_id` como campos obligatorios.

### 6. Open source y stack abierto

Todas las dependencias del flujo principal son open source y self-hostable. No hay vendor lock-in.

**Implicación práctica:** stack aprobado para v1: Python, faster-whisper, Ollama, Qdrant, Obsidian, FastAPI, Git. Cualquier nueva dependencia debe documentarse y justificarse.

### 7. Diseñado para 6 personas, no para escala masiva

Enigma optimiza para un equipo pequeño: baja latencia, baja complejidad operativa, sin clusters, sin orquestadores. No se sacrifica simplicidad por escalabilidad teórica.

**Implicación práctica:** prohibido introducir Kubernetes, microservicios distribuidos o colas externas (Kafka, RabbitMQ) en v1. Una cola en memoria o SQLite basta.

### 8. Privacidad por defecto

Las conversaciones pueden contener información estratégica, personal o confidencial. El sistema asume confidencialidad total.

**Implicación práctica:** logs sin PII en claro, audios cifrados en reposo (opcional v2), sin telemetría externa, sin analytics.

### 9. Spec-driven, no vibe-driven

Toda funcionalidad nueva pasa por: `spec → plan → tasks → código`. Los documentos `SPEC.md`, `PLAN.md` y `TASKS.md` se actualizan **antes** de escribir código, no después.

**Implicación práctica:** un PR sin actualización de specs (cuando corresponda) se rechaza.

### 10. El grafo es el producto

El valor de Enigma no son las notas individuales, sino las conexiones entre ellas. Toda decisión de diseño se evalúa por cómo enriquece o empobrece el grafo.

**Implicación práctica:** una nota sin al menos un `[[wikilink]]` o un `#tag` se marca como huérfana y entra en cola de revisión.

---

## Enmiendas

Para modificar este documento:

1. Abrir un issue titulado `Constitution amendment: <título>`.
2. Justificar qué principio se modifica y por qué.
3. Requerir aprobación de al menos 2/3 del equipo.
4. Actualizar la versión en el encabezado.

---

## Glosario rápido

| Término | Definición |
|---|---|
| **Vault** | Carpeta de Obsidian con todas las notas en Markdown |
| **Nota atómica** | Markdown con una sola idea, frontmatter YAML y enlaces |
| **Wikilink** | Enlace `[[Nota destino]]` entre notas |
| **Call** | Una llamada grabada que origina una o varias notas |
| **Embedding** | Vector numérico que representa el significado de una nota |
| **Agente** | Componente IA que analiza el corpus completo (decisiones, contradicciones, etc.) |
