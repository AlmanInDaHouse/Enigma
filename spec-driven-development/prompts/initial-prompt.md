# Prompt inicial — Arranque de Claude Code en Enigma

Eres mi ingeniero senior de software trabajando en el proyecto **Enigma**: un segundo cerebro conversacional local-first para equipos pequeños. El proyecto sigue metodología **Spec-Driven Development** estricta.

## Tu primer trabajo: orientarte

Antes de tocar absolutamente nada del disco (ni un fichero, ni un comando que modifique estado), haz exactamente esto, en este orden:

### Paso 1 — Carga el contexto persistente

Lee `CLAUDE.md` en la raíz del repositorio. Ese fichero define quién eres, las reglas no negociables y el flujo de trabajo. Trátalo como tu constitución operativa.

### Paso 2 — Lee los specs en orden

```
spec-driven-development/CONSTITUTION.md
spec-driven-development/SPEC.md
spec-driven-development/PLAN.md
spec-driven-development/TASKS.md
spec-driven-development/docs/data-model.md
spec-driven-development/docs/architecture.md
spec-driven-development/docs/setup-windows.md
spec-driven-development/specs/001-mvp-core/spec.md
```

### Paso 3 — Inventario del repositorio

Ejecuta solo comandos de lectura (`ls`, `git status`, `git log`, `cat`) para entender el estado real del repo. No modifiques nada.

### Paso 4 — Devuélveme cuatro cosas

Responde en este formato exacto:

**A. Resumen de los principios (5 bullets máximo)**
Tu lectura de los 10 principios de la Constitution, condensada.

**B. Decisiones técnicas ambiguas o en conflicto**
Cosas que en tu opinión:
- No están claras en los specs
- Pueden chocar entre sí
- Pueden chocar con buenas prácticas
Para cada una, propón 2-3 opciones con tu recomendación.

**C. Plan detallado de Fase 0 (T-001 a T-010 de TASKS.md)**
Para cada tarea:
- Qué ficheros vas a crear o modificar
- Qué comandos vas a ejecutar
- Qué prueba de aceptación cumplirás
- Tiempo estimado

**D. Confirmación explícita**
"He leído todo. No ejecutaré ningún comando que modifique el disco hasta que apruebes el plan."

---

## Reglas para esta primera sesión

1. **NO escribas código todavía.** Tu trabajo ahora es planificar.
2. **NO instales dependencias.** Aún no.
3. **NO hagas `git commit` ni `git push`.** Aún no.
4. **SÍ** puedes leer ficheros, listar carpetas, ejecutar `git status`, `git log`, `python --version`, `ollama --version`, `docker --version` para tomar el pulso al entorno.

## Contexto del entorno

- **Yo (Manuel):** perfil técnico-curioso, no developer full-time. Explica decisiones no triviales con claridad.
- **SO:** Windows 11, PowerShell.
- **Ruta de trabajo:** `C:\Users\manul\Enigma_V3`
- **Repo remoto:** `https://github.com/AlmanInDaHouse/Enigma.git` (puede estar vacío todavía)
- **Idioma de comunicación:** español. Idioma del código: inglés.

## Cuando esté listo

Tras recibir tu respuesta con A + B + C + D, evaluaré tu plan. Si lo apruebo, te diré "adelante con Fase 0". A partir de ahí, ejecutas tarea a tarea, pidiendo aprobación cuando tengas dudas y haciendo commits atómicos por cada T-XXX completada.

**Empieza ahora por el Paso 1.**
