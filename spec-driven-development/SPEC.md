# Enigma — Especificación Funcional (SPEC)

> **Versión:** 1.0 · **Estado:** Borrador inicial · **Audiencia:** product + engineering
> **Alcance:** describe **qué** hace Enigma, no cómo se implementa (eso es `PLAN.md`).

---

## 1. Problema

Los equipos pequeños mantienen la mayoría de su conocimiento crítico en **llamadas síncronas** (reuniones, brainstorms, 1:1, calls con cliente). Ese conocimiento se pierde porque:

- Las grabaciones son inmanejables (1h de audio = 0 valor consultable).
- Los actas manuales son sesgadas y se escriben tarde.
- Las notas individuales viven en herramientas distintas (Notion, Apple Notes, papel).
- Nadie recuerda dónde se decidió X o qué se dijo sobre Y hace 3 meses.

**Resultado:** se repiten decisiones, se contradicen acuerdos previos, las ideas buenas se evaporan.

## 2. Visión

Cada llamada queda automáticamente convertida en **notas atómicas conectadas** dentro de un Vault de Obsidian compartido. El equipo puede preguntar al sistema en lenguaje natural y obtener respuestas con citas verificables hacia las notas originales. El grafo de conocimiento crece con cada llamada en lugar de degradarse.

## 3. Usuarios

| Rol | Cantidad | Necesidades clave |
|---|---|---|
| **Admin** | 1 | Configurar el sistema, gestionar usuarios, supervisar el pipeline |
| **Contribuidor** | hasta 5 | Subir/grabar llamadas, revisar notas extraídas, consultar el grafo |

Total máximo: **6 personas concurrentes**.

## 4. Casos de uso principales

### CU-01 · Capturar una llamada
Un contribuidor inicia una grabación (o sube un fichero de audio ya existente). El sistema acepta `.wav`, `.mp3`, `.m4a`, `.ogg`. La grabación se asocia a un *call_id* único.

### CU-02 · Transcribir automáticamente
La grabación se transcribe a texto con diarización (quién dijo qué, cuándo). El resultado se guarda como artefacto recuperable.

### CU-03 · Extraer notas atómicas
La transcripción se procesa con LLM local. Por cada idea distinta detectada se crea **una nota Markdown** en el Vault con:
- Frontmatter YAML (metadatos)
- Cuerpo de la idea (1–3 párrafos máximo)
- Sección de enlaces `[[wikilinks]]` a notas previas relacionadas
- Tags `#tema/subtema`
- Cita al timestamp original de la llamada

### CU-04 · Conectar al grafo
El sistema busca notas existentes semánticamente similares y propone enlaces. Si la confianza supera el umbral, los crea automáticamente; si no, los marca como sugerencias en una sección `## Sugerencias` de la nota.

### CU-05 · Vectorizar
Cada nota nueva o modificada se vectoriza y se *upsertea* en Qdrant con su `source_id`.

### CU-06 · Buscar semánticamente
Un usuario lanza una consulta en lenguaje natural (`"¿qué decidimos sobre la estrategia de captación de padel clubs?"`). El sistema:
1. Embebe la consulta
2. Recupera top-k notas relevantes
3. Pasa el contexto al LLM
4. Devuelve respuesta con citas `[[Nota]]` a las fuentes

### CU-07 · Análisis transversal por agente
El agente puede ejecutar tareas sobre el corpus completo:
- **Resumen ejecutivo** de una llamada o periodo
- **Lista de decisiones** tomadas (con fecha y contexto)
- **Lista de tareas pendientes** mencionadas
- **Detección de contradicciones** entre llamadas
- **Ideas recurrentes** que aparecen en varias conversaciones
- **Conexiones no obvias** entre notas distantes en el grafo

### CU-08 · Revisar y editar
Un contribuidor abre Obsidian y ve las notas como Markdown normal. Puede editar, refinar, fusionar o borrar. Los cambios se sincronizan vía Git y se re-vectorizan en el siguiente ciclo.

## 5. Requisitos funcionales (RF)

| ID | Requisito | Prioridad |
|---|---|---|
| RF-01 | Aceptar audio en `.wav`, `.mp3`, `.m4a`, `.ogg` hasta 4 horas de duración | Must |
| RF-02 | Transcribir con WER ≤ 15% en español neutro de calidad telefónica | Must |
| RF-03 | Diarización con al menos 2 hablantes distinguibles | Should |
| RF-04 | Extraer entre 5 y 30 notas atómicas por hora de llamada | Must |
| RF-05 | Cada nota tiene frontmatter YAML válido con campos obligatorios | Must |
| RF-06 | Cada nota tiene al menos 1 wikilink **o** entra en cola de revisión | Must |
| RF-07 | Búsqueda semántica devuelve top-k resultados en < 3s para Vault ≤ 5.000 notas | Must |
| RF-08 | El agente genera resúmenes ejecutivos a partir de un rango de fechas | Must |
| RF-09 | El agente detecta contradicciones (notas con afirmaciones opuestas sobre la misma entidad) | Should |
| RF-10 | Reprocesar una llamada no duplica notas (idempotencia) | Must |
| RF-11 | Borrar una nota del Vault la elimina de Qdrant en el siguiente sync | Must |
| RF-12 | El sistema funciona offline una vez instalado (sin internet) | Must |
| RF-13 | CLI mínima para: ingerir, listar, consultar, reindexar | Must |
| RF-14 | API REST local para integraciones futuras | Should |

## 6. Requisitos no funcionales (RNF)

| ID | Requisito | Métrica objetivo |
|---|---|---|
| RNF-01 | **Privacidad:** ningún dato sale del entorno local | 0 llamadas a APIs externas en flujo principal |
| RNF-02 | **Latencia de ingesta:** transcripción + extracción < 1.5× duración del audio | 1h audio → ≤ 90 min procesamiento |
| RNF-03 | **Latencia de consulta:** búsqueda semántica < 3s | p95 < 3s |
| RNF-04 | **Disponibilidad:** servicio local, sin SLA formal | "best effort" en máquina del admin |
| RNF-05 | **Escala:** soporte hasta 6 usuarios y 10.000 notas | sin degradación notable |
| RNF-06 | **Hardware mínimo:** funciona en una máquina con 16GB RAM y GPU opcional | CPU-only funcional, GPU acelera |
| RNF-07 | **Reproducibilidad:** todo el setup se levanta con `docker-compose up` + script de bootstrap | < 30 min desde repo limpio |
| RNF-08 | **Observabilidad:** logs estructurados, métricas básicas (notas/día, latencias) | accesibles en CLI |

## 7. Fuera de alcance (v1)

Explícitamente **no** entran en v1:

- Grabación en tiempo real durante la llamada (v1 procesa audios ya grabados o post-llamada)
- App móvil
- Integraciones con Zoom/Meet/Teams (vía API)
- Transcripción multiidioma simultánea
- Análisis emocional o de sentimiento
- Generación de vídeo o highlights
- Roles/permisos granulares (todos los usuarios ven todas las notas en v1)

## 8. Criterios de éxito

Enigma v1 se considera exitoso cuando:

1. El equipo procesa **≥ 80% de sus llamadas** durante 1 mes consecutivo.
2. Al menos **50% de las consultas semánticas** devuelven una respuesta útil según evaluación del equipo.
3. El grafo tiene **densidad media ≥ 2 enlaces por nota** tras 3 meses de uso.
4. Se identifican **≥ 3 contradicciones o conexiones no obvias** que generen acción.

## 9. Modelo de datos resumen

Detalle completo en [`docs/data-model.md`](docs/data-model.md). Tres entidades principales:

- **Call** — una llamada grabada
- **Transcript** — su transcripción con timestamps y hablantes
- **Note** — una idea atómica derivada (es el ciudadano de primera clase del sistema)

## 10. Referencias

- [Constitution](CONSTITUTION.md) — principios inmutables
- [Plan técnico](PLAN.md) — cómo se implementa
- [Tasks](TASKS.md) — desglose accionable
- [Modelo de datos](docs/data-model.md)
- [Arquitectura](docs/architecture.md)
