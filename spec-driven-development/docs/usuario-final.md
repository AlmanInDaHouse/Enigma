# Enigma — Guía de usuario

> Para los miembros del equipo que usan Enigma desde **Obsidian**, sin tocar
> la terminal ni el código. Si te encargas de instalar o mantener el sistema,
> mira `setup-windows.md`.

---

## Qué es Enigma

Enigma es el **segundo cerebro del equipo**. Coge las llamadas que grabáis y
las convierte, solas, en una red de notas navegable dentro de Obsidian: cada
idea importante queda como una nota corta, conectada con las ideas
relacionadas de otras llamadas.

Tú no tienes que escribir esas notas. Tu trabajo es **grabar las llamadas**,
**revisar lo que el sistema propone** y **consultar** el conocimiento
acumulado.

---

## El flujo, de un vistazo

```
Grabas una llamada  ──►  Enigma la procesa  ──►  Notas en Obsidian  ──►  Tú revisas y consultas
```

1. **Grabáis una llamada** y guardáis el audio.
2. La persona que mantiene Enigma lo procesa (un comando). De ahí salen:
   - una **nota de la llamada** (resumen + enlaces),
   - varias **notas atómicas** (una idea cada una),
   - todo conectado en el grafo.
3. Esas notas aparecen en **tu Obsidian** automáticamente (se sincroniza solo).
4. Tú **revisas** las notas nuevas y **preguntas** al sistema cuando necesites
   recuperar algo.

---

## Cómo está organizado el Vault

Al abrir Obsidian verás estas carpetas:

| Carpeta / fichero | Qué contiene |
|---|---|
| `inbox/` | Notas recién extraídas, **pendientes de tu revisión**. |
| `notes/` | Notas ya revisadas y validadas — el conocimiento "en limpio". |
| `calls/` | Una nota por llamada: resumen y enlaces a sus notas atómicas. |
| `decisions.md` | Todas las **decisiones** tomadas, por llamada. |
| `tasks.md` | Las **tareas pendientes** mencionadas, con responsable si se sabe. |
| `recurring-themes.md` | **Ideas que reaparecen** en varias llamadas. |
| `contradictions.md` | Notas que **se contradicen** entre sí — para aclarar. |
| `serendipity.md` | **Conexiones sorprendentes** entre notas distantes. |

---

## Qué es una nota atómica

Cada nota es **una sola idea**, corta, en su propio fichero. Tiene tres
partes:

- **El cuerpo:** la idea, en uno o dos párrafos.
- **`## Conexiones`:** enlaces `[[a otras notas]]` relacionadas. Pínchalos
  para saltar de una idea a otra.
- **`## Origen`:** de qué llamada y minuto sale la nota — su trazabilidad.

En la **vista de grafo** de Obsidian (el icono de los círculos conectados)
verás cómo se enlazan. Esa red es el producto: cuanto más rica, más valor.

---

## Tu tarea: revisar el `inbox/`

Las notas nuevas llegan a `inbox/` como **borradores**. Revisarlas es lo único
que se te pide de forma recurrente:

1. Abre una nota de `inbox/`.
2. Léela. ¿La idea está bien capturada? ¿El título es claro?
3. Si está bien: **muévela a `notes/`** (arrástrala en el panel de archivos de
   Obsidian) y cambia `status: draft` por `status: validated` en la cabecera.
4. Si está mal o sobra: corrígela o bórrala.

Las notas marcadas con la etiqueta **`#orphan`** son las que no tienen ninguna
conexión — conviene revisarlas, porque una idea aislada suele indicar que
falta enlazarla o que no aporta.

> No hace falta que vacíes el `inbox/` de golpe. Revisa lo que puedas; el
> sistema no se rompe por tener borradores acumulados.

---

## Consultar el conocimiento

Hay dos formas, según quien las pida:

**Desde Obsidian (cualquiera):**
- Usa la **búsqueda** de Obsidian (`Ctrl+Shift+F`) para texto literal.
- Navega por los índices: abre `decisions.md`, `tasks.md`,
  `recurring-themes.md`… para ver el panorama transversal.
- Sigue los `[[enlaces]]` y la vista de grafo para explorar.

**Preguntas en lenguaje natural:**
- Enigma puede responder preguntas tipo *"¿qué decidimos sobre los precios?"*
  citando las notas que lo respaldan.
- Esto lo lanza quien mantiene el sistema (comando `enigma ask`), o se expone
  como un servicio interno. Pídeselo si necesitas una respuesta razonada y no
  solo encontrar un fichero.

---

## Buenas prácticas al grabar llamadas

Cuanto mejor el audio, mejores las notas:

- Graba en un sitio **sin ruido de fondo**.
- Que **se hable claro** y por turnos (evitad pisaros — ayuda a distinguir
  quién dice qué).
- Audio de **al menos 30 segundos**; formatos `.wav`, `.mp3`, `.m4a`, `.ogg`.
- Pon un **título descriptivo** a la grabación; será el nombre de la llamada.

---

## Preguntas frecuentes

**¿Tengo que escribir notas a mano?**
No. Enigma las extrae. Tú revisas y, si quieres, corriges.

**¿Puedo editar una nota generada?**
Sí. Es un fichero Markdown normal de Obsidian. Tus cambios se conservan.

**¿Y si reproceso la misma llamada?**
No se duplica nada. Enigma es idempotente: la misma llamada produce siempre
las mismas notas, en el mismo sitio.

**Veo un conflicto de Git en Obsidian.**
Pasa raramente cuando dos personas editan a la vez. Pulsa `Ctrl+P` →
`Git: Pull`, resuelve el choque en el `.md` y `Git: Commit and push`. Si te
atascas, avisa a quien mantiene el sistema.

**Una nota dice algo que ya no es cierto.**
Edítala o bórrala. Y revisa `contradictions.md`: puede que el sistema ya haya
detectado el choque con otra nota.

**¿Mis datos salen de aquí?**
No. Enigma es **local**: la transcripción, el modelo de lenguaje y la base de
datos corren en una máquina del equipo. Nada se envía a servicios externos.
