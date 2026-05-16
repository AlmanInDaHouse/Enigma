"use strict";

/* Enigma — frontend. Habla con la API local (mismo origen): /stats, /search, /ask. */

const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/* ── Constelación de fondo ───────────────────────────────────────────── */

function initConstellation() {
  const canvas = document.getElementById("constellation");
  const ctx = canvas.getContext("2d");
  let nodes = [];
  let width = 0;
  let height = 0;

  function resize() {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    width = window.innerWidth;
    height = window.innerHeight;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const target = Math.min(66, Math.round((width * height) / 26000));
    nodes = Array.from({ length: target }, () => ({
      x: Math.random() * width,
      y: Math.random() * height,
      vx: (Math.random() - 0.5) * 0.16,
      vy: (Math.random() - 0.5) * 0.16,
      r: Math.random() * 1.6 + 0.7,
      warm: Math.random() > 0.7,
    }));
  }

  function frame() {
    ctx.clearRect(0, 0, width, height);
    for (const n of nodes) {
      n.x += n.vx;
      n.y += n.vy;
      if (n.x < 0 || n.x > width) n.vx *= -1;
      if (n.y < 0 || n.y > height) n.vy *= -1;
    }
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const a = nodes[i];
        const b = nodes[j];
        const dist = Math.hypot(a.x - b.x, a.y - b.y);
        if (dist < 132) {
          ctx.strokeStyle = `rgba(150,150,160,${(1 - dist / 132) * 0.13})`;
          ctx.lineWidth = 0.6;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      }
    }
    for (const n of nodes) {
      ctx.fillStyle = n.warm ? "rgba(236,180,85,0.55)" : "rgba(150,160,170,0.4)";
      ctx.beginPath();
      ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
      ctx.fill();
    }
    if (!REDUCED_MOTION) requestAnimationFrame(frame);
  }

  resize();
  window.addEventListener("resize", resize);
  frame();
}

/* ── Utilidades ──────────────────────────────────────────────────────── */

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

/* Convierte los `[[stem|título]]` de una respuesta en marcas de cita. */
function renderCitations(text) {
  return escapeHtml(text).replace(/\[\[([^\]]+)\]\]/g, (_, inner) => {
    const label = inner.includes("|") ? inner.split("|").slice(1).join("|") : inner;
    return `<span class="cite">${label}</span>`;
  });
}

async function getJSON(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    let detail = `Error ${res.status}`;
    try {
      const body = await res.json();
      if (body && body.detail) detail = body.detail;
    } catch (_) {
      /* respuesta sin cuerpo JSON */
    }
    throw new Error(detail);
  }
  return res.json();
}

/* ── Estado de servicios + estadísticas ──────────────────────────────── */

function setStatus(svc, ok) {
  const pill = document.querySelector(`.status-pill[data-svc="${svc}"]`);
  if (pill) pill.classList.add(ok ? "ok" : "down");
}

function statCard(num, suffix, label, note) {
  const small = suffix ? `<small>${suffix}</small>` : "";
  const noteEl = note ? `<div class="stat-note">${note}</div>` : "";
  return `<div class="stat">
    <div class="stat-num">${num}${small}</div>
    <div class="stat-label">${label}</div>
    ${noteEl}
  </div>`;
}

async function loadStats() {
  const grid = document.getElementById("stat-grid");
  try {
    const data = await getJSON("/stats");
    const c = data.corpus;
    setStatus("qdrant", data.health.qdrant_ok);
    setStatus("ollama", data.health.ollama_ok);

    const validated = (c.notes_by_status && c.notes_by_status.validated) || 0;
    const vectors = c.qdrant_vectors == null ? "—" : c.qdrant_vectors;
    grid.innerHTML =
      statCard(c.total_calls, "", "Llamadas procesadas", null) +
      statCard(
        c.total_notes,
        "",
        "Notas atómicas",
        `${validated} validadas · ${c.orphan_notes} huérfanas`
      ) +
      statCard(vectors, "", "Notas en el grafo", "indexadas en Qdrant") +
      statCard(c.total_audio_hours.toFixed(1), "h", "Audio destilado", null);
  } catch (err) {
    grid.innerHTML = `<p class="results-empty">No se pudieron cargar las métricas: ${escapeHtml(
      err.message
    )}</p>`;
  }
}

/* ── Preguntar (RAG) ─────────────────────────────────────────────────── */

function setupAsk() {
  const form = document.getElementById("ask-form");
  const input = document.getElementById("ask-input");
  const btn = document.getElementById("ask-btn");
  const wrap = document.getElementById("answer-wrap");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const question = input.value.trim();
    if (!question) return;

    btn.disabled = true;
    wrap.hidden = false;
    wrap.innerHTML = `<div class="answer-card">
      <div class="answer-tag">Consultando el grafo</div>
      <div class="thinking"><span class="orb"></span> Enigma está pensando…</div>
    </div>`;
    wrap.scrollIntoView({ behavior: REDUCED_MOTION ? "auto" : "smooth", block: "nearest" });

    try {
      const data = await getJSON("/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      let cites = "";
      if (data.citations && data.citations.length) {
        const chips = data.citations
          .map((cit) => `<span class="chip">${escapeHtml(cit.title)}</span>`)
          .join("");
        cites = `<div class="answer-cites">
          <h4>Notas citadas — ${data.citations.length}</h4>
          <div class="chip-row">${chips}</div>
        </div>`;
      } else {
        cites = `<div class="answer-cites">
          <h4>Notas citadas</h4>
          <p class="answer-empty">La respuesta no se apoya en ninguna nota concreta.</p>
        </div>`;
      }
      wrap.innerHTML = `<div class="answer-card">
        <div class="answer-tag">Respuesta de Enigma</div>
        <div class="answer-q">«&#8202;${escapeHtml(question)}&#8202;»</div>
        <div class="answer-body">${renderCitations(data.answer)}</div>
        ${cites}
      </div>`;
    } catch (err) {
      wrap.innerHTML = `<div class="answer-card error">
        <div class="answer-tag">No se pudo responder</div>
        <div class="answer-body">${escapeHtml(err.message)}</div>
      </div>`;
    } finally {
      btn.disabled = false;
    }
  });
}

/* ── Búsqueda semántica ──────────────────────────────────────────────── */

function setupSearch() {
  const form = document.getElementById("search-form");
  const input = document.getElementById("search-input");
  const results = document.getElementById("search-results");

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const query = input.value.trim();
    if (!query) return;

    results.innerHTML = `<p class="results-hint">Buscando «${escapeHtml(query)}»…</p>`;
    try {
      const hits = await getJSON(`/search?q=${encodeURIComponent(query)}&top_k=8`);
      if (!hits.length) {
        results.innerHTML = `<p class="results-empty">Sin resultados para «${escapeHtml(
          query
        )}». ¿Aún no hay notas indexadas?</p>`;
        return;
      }
      results.innerHTML = hits
        .map((hit) => {
          const tags = (hit.tags || []).length ? "#" + hit.tags.join("  #") : "sin etiquetas";
          return `<div class="result">
            <div class="result-score">${hit.score.toFixed(2)}</div>
            <div class="result-main">
              <div class="result-title">${escapeHtml(hit.title)}</div>
              <div class="result-tags">${escapeHtml(tags)}</div>
            </div>
            <div class="result-status">${escapeHtml(hit.status)}</div>
          </div>`;
        })
        .join("");
    } catch (err) {
      results.innerHTML = `<p class="results-empty">Error en la búsqueda: ${escapeHtml(
        err.message
      )}</p>`;
    }
  });
}

/* ── Arranque ────────────────────────────────────────────────────────── */

initConstellation();
loadStats();
setupAsk();
setupSearch();
