"use strict";

/* Enigma — app del equipo. Chat en vivo (WebSocket) + consulta a la memoria. */

const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const NAME_KEY = "enigma.name";

const state = {
  me: localStorage.getItem(NAME_KEY) || "",
  view: "chat",
  channel: "general",
  channels: ["general"],
  messages: [],
  ws: null,
  statsLoaded: false,
};

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
    const target = Math.min(64, Math.round((width * height) / 28000));
    nodes = Array.from({ length: target }, () => ({
      x: Math.random() * width,
      y: Math.random() * height,
      vx: (Math.random() - 0.5) * 0.15,
      vy: (Math.random() - 0.5) * 0.15,
      r: Math.random() * 1.5 + 0.7,
      warm: Math.random() > 0.72,
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
        if (dist < 128) {
          ctx.strokeStyle = `rgba(150,150,160,${(1 - dist / 128) * 0.12})`;
          ctx.lineWidth = 0.6;
          ctx.beginPath();
          ctx.moveTo(a.x, a.y);
          ctx.lineTo(b.x, b.y);
          ctx.stroke();
        }
      }
    }
    for (const n of nodes) {
      ctx.fillStyle = n.warm ? "rgba(236,180,85,0.5)" : "rgba(150,160,170,0.36)";
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
  div.textContent = text == null ? "" : text;
  return div.innerHTML;
}

const AVATAR_COLORS = ["#ecb455", "#74c4ba", "#c98f6d", "#9a8fd0", "#7fae6b", "#d0879e"];

function avatarColor(name) {
  let hash = 0;
  for (let i = 0; i < name.length; i++) hash = (hash * 31 + name.charCodeAt(i)) | 0;
  return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length];
}

function initials(name) {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  return (parts[0][0] + (parts[1] ? parts[1][0] : "")).toUpperCase();
}

function avatarHtml(name, cls) {
  const color = avatarColor(name);
  return `<span class="avatar ${cls || ""}" style="background:${color}">${escapeHtml(
    initials(name)
  )}</span>`;
}

function timeOf(iso) {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

async function getJSON(url, options) {
  const res = await fetch(url, options);
  if (!res.ok) {
    let detail = `Error ${res.status}`;
    try {
      const body = await res.json();
      if (body && body.detail) detail = body.detail;
    } catch (_) {
      /* sin cuerpo JSON */
    }
    throw new Error(detail);
  }
  return res.json();
}

/* ── Identidad ───────────────────────────────────────────────────────── */

function setupGate() {
  const gate = document.getElementById("name-gate");
  const form = document.getElementById("name-form");
  const input = document.getElementById("name-input");

  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const name = input.value.trim();
    if (!name) return;
    localStorage.setItem(NAME_KEY, name);
    location.reload();
  });

  document.getElementById("me").addEventListener("click", () => {
    input.value = state.me;
    gate.hidden = false;
    input.focus();
  });

  if (state.me) {
    enterApp();
  } else {
    input.focus();
  }
}

function enterApp() {
  document.getElementById("name-gate").hidden = true;
  document.getElementById("app").hidden = false;

  const avatar = document.getElementById("me-avatar");
  avatar.style.background = avatarColor(state.me);
  avatar.textContent = initials(state.me);
  document.getElementById("me-name").textContent = state.me;

  loadChannels();
  connect();
}

/* ── Canales y vistas ────────────────────────────────────────────────── */

async function loadChannels() {
  try {
    state.channels = await getJSON("/channels");
  } catch (_) {
    state.channels = ["general"];
  }
  const list = document.getElementById("channel-list");
  list.innerHTML = state.channels
    .map(
      (ch) =>
        `<li><button class="nav-item" data-channel="${escapeHtml(ch)}">` +
        `<span class="hash">#</span> ${escapeHtml(ch)}</button></li>`
    )
    .join("");
  list.querySelectorAll("[data-channel]").forEach((btn) => {
    btn.addEventListener("click", () => setChannel(btn.dataset.channel));
  });
  document
    .querySelectorAll(".nav-item[data-view]")
    .forEach((btn) => btn.addEventListener("click", () => setView(btn.dataset.view)));
  setChannel(state.channels[0]);
}

function setChannel(channel) {
  state.channel = channel;
  setView("chat");
  document.getElementById("channel-name").textContent = channel;
  document.getElementById("composer-input").placeholder = `Escribe en #${channel}…`;
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.channel === channel);
  });
  renderMessages();
}

function setView(view) {
  state.view = view;
  document.getElementById("view-chat").hidden = view !== "chat";
  document.getElementById("view-enigma").hidden = view !== "enigma";
  if (view === "enigma") {
    document.querySelectorAll(".nav-item").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.view === "enigma");
    });
    if (!state.statsLoaded) {
      state.statsLoaded = true;
      loadStats();
    }
  }
}

/* ── Chat ────────────────────────────────────────────────────────────── */

function renderMessages() {
  const list = document.getElementById("message-list");
  const channelMsgs = state.messages.filter((m) => m.channel === state.channel);

  if (!channelMsgs.length) {
    list.innerHTML = `<p class="empty-chat">Aún no hay mensajes en #${escapeHtml(
      state.channel
    )}. Rompe el hielo.</p>`;
    return;
  }

  let html = "";
  let prevAuthor = null;
  let prevTime = 0;
  for (const m of channelMsgs) {
    const t = new Date(m.created_at).getTime();
    const grouped = m.author === prevAuthor && t - prevTime < 5 * 60 * 1000;
    if (grouped) {
      html += `<div class="msg grouped"><span class="gutter"></span>
        <div class="msg-main"><div class="msg-body">${escapeHtml(m.body)}</div></div></div>`;
    } else {
      html += `<div class="msg fresh">${avatarHtml(m.author)}
        <div class="msg-main">
          <div class="msg-head">
            <span class="msg-author">${escapeHtml(m.author)}</span>
            <span class="msg-time">${timeOf(m.created_at)}</span>
          </div>
          <div class="msg-body">${escapeHtml(m.body)}</div>
        </div></div>`;
    }
    prevAuthor = m.author;
    prevTime = t;
  }
  list.innerHTML = html;
  list.scrollTop = list.scrollHeight;
}

function renderPresence(users) {
  document.getElementById("online-count").textContent = users.length;
  document.getElementById("presence-list").innerHTML = users
    .map(
      (u) =>
        `<li class="presence-item">${avatarHtml(u)} ${escapeHtml(u)}` +
        (u === state.me ? " <span class='msg-time'>· tú</span>" : "") +
        `</li>`
    )
    .join("");
}

function setupComposer() {
  const form = document.getElementById("composer");
  const input = document.getElementById("composer-input");
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const body = input.value.trim();
    if (!body || !state.ws || state.ws.readyState !== WebSocket.OPEN) return;
    state.ws.send(JSON.stringify({ type: "chat", channel: state.channel, body }));
    input.value = "";
  });
}

/* ── WebSocket ───────────────────────────────────────────────────────── */

function setConn(live) {
  const dot = document.getElementById("conn-dot");
  dot.classList.toggle("live", live);
  dot.classList.toggle("lost", !live);
}

function connect() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/ws`);
  state.ws = ws;

  ws.addEventListener("open", () => {
    setConn(true);
    ws.send(JSON.stringify({ type: "hello", name: state.me }));
  });

  ws.addEventListener("message", (event) => {
    const data = JSON.parse(event.data);
    if (data.type === "history") {
      state.messages = data.messages;
      renderMessages();
    } else if (data.type === "chat") {
      state.messages.push(data.message);
      if (data.message.channel === state.channel && state.view === "chat") renderMessages();
    } else if (data.type === "presence") {
      renderPresence(data.users);
    }
  });

  ws.addEventListener("close", () => {
    setConn(false);
    setTimeout(connect, 2500);
  });
  ws.addEventListener("error", () => ws.close());
}

/* ── Enigma: estadísticas ────────────────────────────────────────────── */

function statCard(num, suffix, label, note) {
  const small = suffix ? `<small>${suffix}</small>` : "";
  const noteEl = note ? `<div class="stat-note">${note}</div>` : "";
  return `<div class="stat"><div class="stat-num">${num}${small}</div>
    <div class="stat-label">${label}</div>${noteEl}</div>`;
}

async function loadStats() {
  const grid = document.getElementById("stat-grid");
  try {
    const data = await getJSON("/stats");
    const c = data.corpus;
    const validated = (c.notes_by_status && c.notes_by_status.validated) || 0;
    const vectors = c.qdrant_vectors == null ? "—" : c.qdrant_vectors;
    grid.innerHTML =
      statCard(c.total_calls, "", "Llamadas procesadas", null) +
      statCard(c.total_notes, "", "Notas atómicas", `${validated} validadas`) +
      statCard(vectors, "", "Notas en el grafo", "indexadas en Qdrant") +
      statCard(c.total_audio_hours.toFixed(1), "h", "Audio destilado", null);
  } catch (err) {
    grid.innerHTML = `<p class="results-empty">No se pudieron cargar las métricas: ${escapeHtml(
      err.message
    )}</p>`;
  }
}

/* ── Enigma: preguntar (RAG) ─────────────────────────────────────────── */

function renderCitations(text) {
  return escapeHtml(text).replace(/\[\[([^\]]+)\]\]/g, (_, inner) => {
    const label = inner.includes("|") ? inner.split("|").slice(1).join("|") : inner;
    return `<span class="cite">${label}</span>`;
  });
}

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
    wrap.innerHTML = `<div class="answer-card"><div class="answer-tag">Consultando el grafo</div>
      <div class="thinking"><span class="orb"></span> Enigma está pensando…</div></div>`;

    try {
      const data = await getJSON("/ask", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question }),
      });
      let cites;
      if (data.citations && data.citations.length) {
        const chips = data.citations
          .map((c) => `<span class="chip">${escapeHtml(c.title)}</span>`)
          .join("");
        cites = `<div class="answer-cites"><h4>Notas citadas — ${data.citations.length}</h4>
          <div class="chip-row">${chips}</div></div>`;
      } else {
        cites = `<div class="answer-cites"><h4>Notas citadas</h4>
          <p class="answer-empty">La respuesta no se apoya en ninguna nota concreta.</p></div>`;
      }
      wrap.innerHTML = `<div class="answer-card">
        <div class="answer-tag">Respuesta de Enigma</div>
        <div class="answer-q">«&#8202;${escapeHtml(question)}&#8202;»</div>
        <div class="answer-body">${renderCitations(data.answer)}</div>${cites}</div>`;
    } catch (err) {
      wrap.innerHTML = `<div class="answer-card error">
        <div class="answer-tag">No se pudo responder</div>
        <div class="answer-body">${escapeHtml(err.message)}</div></div>`;
    } finally {
      btn.disabled = false;
    }
  });
}

/* ── Enigma: búsqueda ────────────────────────────────────────────────── */

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
        )}».</p>`;
        return;
      }
      results.innerHTML = hits
        .map((hit) => {
          const tags = (hit.tags || []).length ? "#" + hit.tags.join("  #") : "sin etiquetas";
          return `<div class="result"><div class="result-score">${hit.score.toFixed(2)}</div>
            <div class="result-main"><div class="result-title">${escapeHtml(hit.title)}</div>
            <div class="result-tags">${escapeHtml(tags)}</div></div>
            <div class="result-status">${escapeHtml(hit.status)}</div></div>`;
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
setupGate();
setupComposer();
setupAsk();
setupSearch();
