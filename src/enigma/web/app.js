"use strict";

/* Enigma — app del equipo. Chat + llamadas WebRTC + consulta a la memoria. */

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
  call: {
    joined: false,
    myPeerId: null,
    iceServers: [],
    peers: new Map(), // peerId -> { pc, stream }
    names: new Map(), // peerId -> name
    roster: new Set(), // peerIds (otros) en la llamada
    localStream: null,
    screenStream: null,
    micOn: true,
    camOn: true,
    recording: false,
    recorder: null,
    audioCtx: null,
    mixDest: null,
    mixedSources: null,
    recChunks: [],
  },
};

const CALL_STATUS = {
  pending: { label: "en cola", cls: "work" },
  transcribing: { label: "transcribiendo", cls: "work" },
  extracting: { label: "extrayendo notas", cls: "work" },
  done: { label: "listo", cls: "done" },
  failed: { label: "error", cls: "fail" },
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
  return `<span class="avatar ${cls || ""}" style="background:${avatarColor(name)}">${escapeHtml(
    initials(name)
  )}</span>`;
}

function timeOf(iso) {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
}

let toastTimer = null;
function toast(message) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    el.hidden = true;
  }, 4200);
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
  document.getElementById("channel-name").textContent = channel;
  document.getElementById("composer-input").placeholder = `Escribe en #${channel}…`;
  setView("chat");
  renderMessages();
}

function setView(view) {
  state.view = view;
  for (const v of ["chat", "call", "enigma"]) {
    document.getElementById(`view-${v}`).hidden = view !== v;
  }
  document.querySelectorAll(".nav-item").forEach((btn) => {
    const isChannel = view === "chat" && btn.dataset.channel === state.channel;
    const isView = btn.dataset.view === view;
    btn.classList.toggle("active", isChannel || isView);
  });
  if (view === "call") renderCallView();
  if (view === "enigma" && !state.statsLoaded) {
    state.statsLoaded = true;
    loadStats();
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

function handleWsMessage(data) {
  switch (data.type) {
    case "welcome":
      state.call.myPeerId = data.peer_id;
      state.call.iceServers = data.ice_servers || [];
      break;
    case "history":
      state.messages = data.messages;
      renderMessages();
      break;
    case "chat":
      state.messages.push(data.message);
      if (data.message.channel === state.channel && state.view === "chat") renderMessages();
      break;
    case "presence":
      renderPresence(data.users);
      break;
    case "call-roster":
      onCallRoster(data.peers);
      break;
    case "call-joined":
      state.call.names.set(data.peer_id, data.name);
      if (data.peer_id !== state.call.myPeerId) state.call.roster.add(data.peer_id);
      updateCallBadge();
      break;
    case "call-left":
      state.call.roster.delete(data.peer_id);
      closePeer(data.peer_id);
      updateCallBadge();
      break;
    case "signal":
      handleSignal(data.from, data.data);
      break;
    default:
      break;
  }
}

function connect() {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/ws`);
  state.ws = ws;

  ws.addEventListener("open", () => {
    setConn(true);
    ws.send(JSON.stringify({ type: "hello", name: state.me }));
  });
  ws.addEventListener("message", (event) => handleWsMessage(JSON.parse(event.data)));
  ws.addEventListener("close", () => {
    setConn(false);
    setTimeout(connect, 2500);
  });
  ws.addEventListener("error", () => ws.close());
}

function wsSend(payload) {
  if (state.ws && state.ws.readyState === WebSocket.OPEN) {
    state.ws.send(JSON.stringify(payload));
  }
}

/* ── Llamadas (WebRTC) ───────────────────────────────────────────────── */

function updateCallBadge() {
  const count = state.call.roster.size + (state.call.joined ? 1 : 0);
  const badge = document.getElementById("call-count");
  badge.textContent = count;
  badge.hidden = count === 0;
  document
    .querySelector('.nav-item[data-view="call"]')
    .classList.toggle("in-call", state.call.joined);
}

function sendSignal(toPeerId, data) {
  wsSend({ type: "signal", to: toPeerId, data });
}

function createPeer(peerId, isInitiator) {
  if (state.call.peers.has(peerId)) return state.call.peers.get(peerId);
  const pc = new RTCPeerConnection({
    iceServers: state.call.iceServers.map((url) => ({ urls: url })),
  });
  const entry = { pc, stream: null };
  state.call.peers.set(peerId, entry);

  for (const track of state.call.localStream.getTracks()) {
    pc.addTrack(track, state.call.localStream);
  }
  pc.addEventListener("icecandidate", (event) => {
    if (event.candidate) sendSignal(peerId, { candidate: event.candidate });
  });
  pc.addEventListener("track", (event) => {
    entry.stream = event.streams[0];
    if (state.call.recording) addToMix(entry.stream);
    syncTiles();
  });
  pc.addEventListener("connectionstatechange", () => {
    if (pc.connectionState === "failed" || pc.connectionState === "closed") closePeer(peerId);
  });

  if (isInitiator) {
    pc.createOffer()
      .then((offer) => pc.setLocalDescription(offer))
      .then(() => sendSignal(peerId, { desc: pc.localDescription }))
      .catch(() => closePeer(peerId));
  }
  syncTiles();
  return entry;
}

async function handleSignal(from, data) {
  if (!state.call.joined) return;
  let entry = state.call.peers.get(from);
  if (!entry) entry = createPeer(from, false);
  const pc = entry.pc;
  try {
    if (data.desc) {
      await pc.setRemoteDescription(data.desc);
      if (data.desc.type === "offer") {
        const answer = await pc.createAnswer();
        await pc.setLocalDescription(answer);
        sendSignal(from, { desc: pc.localDescription });
      }
    } else if (data.candidate) {
      await pc.addIceCandidate(data.candidate);
    }
  } catch (_) {
    /* señal fuera de orden o par ya cerrado */
  }
}

function onCallRoster(peers) {
  for (const peer of peers) {
    state.call.names.set(peer.peer_id, peer.name);
    state.call.roster.add(peer.peer_id);
    createPeer(peer.peer_id, true); // somos los recién llegados: ofrecemos
  }
  updateCallBadge();
}

function closePeer(peerId) {
  const entry = state.call.peers.get(peerId);
  if (entry) {
    try {
      entry.pc.close();
    } catch (_) {
      /* ya cerrado */
    }
    state.call.peers.delete(peerId);
  }
  syncTiles();
}

async function joinCall() {
  try {
    state.call.localStream = await navigator.mediaDevices.getUserMedia({
      video: true,
      audio: true,
    });
  } catch (err) {
    renderLobby(`No se pudo acceder a la cámara o el micrófono: ${err.message}`);
    return;
  }
  state.call.joined = true;
  state.call.micOn = true;
  state.call.camOn = true;
  wsSend({ type: "call-join" });
  updateCallBadge();
  renderCallView();
}

function leaveCall() {
  if (state.call.recording) stopRecording();
  wsSend({ type: "call-leave" });
  for (const peerId of [...state.call.peers.keys()]) closePeer(peerId);
  for (const stream of [state.call.localStream, state.call.screenStream]) {
    if (stream) stream.getTracks().forEach((t) => t.stop());
  }
  state.call.localStream = null;
  state.call.screenStream = null;
  state.call.joined = false;
  updateCallBadge();
  renderCallView();
}

function replaceVideoTrack(track) {
  for (const { pc } of state.call.peers.values()) {
    const sender = pc.getSenders().find((s) => s.track && s.track.kind === "video");
    if (sender) sender.replaceTrack(track);
  }
  const localVideo = document.querySelector("#tile-local video");
  if (localVideo) {
    localVideo.srcObject = new MediaStream([track, ...state.call.localStream.getAudioTracks()]);
  }
}

function toggleMic() {
  const track = state.call.localStream && state.call.localStream.getAudioTracks()[0];
  if (!track) return;
  state.call.micOn = !state.call.micOn;
  track.enabled = state.call.micOn;
  renderControls();
  syncTiles();
}

function toggleCam() {
  const track = state.call.localStream && state.call.localStream.getVideoTracks()[0];
  if (!track || state.call.screenStream) return;
  state.call.camOn = !state.call.camOn;
  track.enabled = state.call.camOn;
  renderControls();
  syncTiles();
}

async function toggleScreen() {
  if (state.call.screenStream) {
    state.call.screenStream.getTracks().forEach((t) => t.stop());
    state.call.screenStream = null;
    replaceVideoTrack(state.call.localStream.getVideoTracks()[0]);
    renderControls();
    return;
  }
  let display;
  try {
    display = await navigator.mediaDevices.getDisplayMedia({ video: true });
  } catch (_) {
    return; // el usuario canceló
  }
  state.call.screenStream = display;
  const screenTrack = display.getVideoTracks()[0];
  screenTrack.addEventListener("ended", () => {
    if (state.call.screenStream) toggleScreen();
  });
  replaceVideoTrack(screenTrack);
  renderControls();
}

/* ── Grabación de la llamada ─────────────────────────────────────────── */

function addToMix(stream) {
  if (!stream || !state.call.mixDest || !state.call.mixedSources) return;
  if (state.call.mixedSources.has(stream) || !stream.getAudioTracks().length) return;
  state.call.audioCtx.createMediaStreamSource(stream).connect(state.call.mixDest);
  state.call.mixedSources.add(stream);
}

function startRecording() {
  if (!state.call.localStream) return;
  const Ctx = window.AudioContext || window.webkitAudioContext;
  state.call.audioCtx = new Ctx();
  state.call.mixDest = state.call.audioCtx.createMediaStreamDestination();
  state.call.mixedSources = new Set();
  addToMix(state.call.localStream);
  for (const entry of state.call.peers.values()) addToMix(entry.stream);
  state.call.recChunks = [];
  let recorder;
  try {
    recorder = new MediaRecorder(state.call.mixDest.stream, { mimeType: "audio/webm" });
  } catch (_) {
    recorder = new MediaRecorder(state.call.mixDest.stream);
  }
  recorder.addEventListener("dataavailable", (event) => {
    if (event.data && event.data.size) state.call.recChunks.push(event.data);
  });
  recorder.addEventListener("stop", uploadRecording);
  recorder.start();
  state.call.recorder = recorder;
  state.call.recording = true;
  renderControls();
  toast("Grabando la llamada. Al parar, se convertirá en notas.");
}

function stopRecording() {
  state.call.recording = false;
  renderControls();
  if (state.call.recorder && state.call.recorder.state !== "inactive") {
    state.call.recorder.stop(); // dispara uploadRecording
  }
}

function toggleRecording() {
  if (state.call.recording) stopRecording();
  else startRecording();
}

async function uploadRecording() {
  const blob = new Blob(state.call.recChunks, { type: "audio/webm" });
  state.call.recChunks = [];
  if (state.call.audioCtx) {
    state.call.audioCtx.close();
    state.call.audioCtx = null;
  }
  state.call.recorder = null;
  state.call.mixDest = null;
  state.call.mixedSources = null;
  if (!blob.size) return;
  const title = `Llamada del equipo — ${new Date().toLocaleString("es-ES")}`;
  toast("Subiendo la grabación a Enigma…");
  try {
    const res = await fetch(`/calls/upload?title=${encodeURIComponent(title)}`, {
      method: "POST",
      body: blob,
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    toast("Grabación enviada. Enigma la está convirtiendo en notas.");
    loadCalls();
  } catch (err) {
    toast(`No se pudo subir la grabación: ${err.message}`);
  }
}

async function loadCalls() {
  const box = document.getElementById("lobby-calls");
  if (!box) return;
  let calls;
  try {
    calls = await getJSON("/calls");
  } catch (_) {
    return;
  }
  if (!calls.length) {
    box.innerHTML =
      '<p class="nav-label">Llamadas</p>' +
      '<p class="results-empty">Aún no se ha procesado ninguna llamada.</p>';
    return;
  }
  box.innerHTML =
    '<p class="nav-label">Llamadas procesadas</p>' +
    calls
      .map((call) => {
        const st = CALL_STATUS[call.status] || { label: call.status, cls: "" };
        const when = new Date(call.recorded_at).toLocaleString("es-ES");
        const mins = (call.duration_seconds / 60).toFixed(1);
        const title = call.title || "Llamada";
        return `<div class="call-row clickable" data-id="${escapeHtml(call.id)}"
            data-title="${escapeHtml(title)}" data-status="${escapeHtml(call.status)}">
          <div class="call-row-main">
            <div class="call-row-title">${escapeHtml(title)}</div>
            <div class="call-row-meta">${escapeHtml(when)} · ${mins} min</div>
          </div>
          <span class="call-status ${st.cls}">${escapeHtml(st.label)}</span>
        </div>`;
      })
      .join("");
  box.querySelectorAll(".call-row").forEach((row) => {
    row.addEventListener("click", () =>
      openCallNotes(row.dataset.id, row.dataset.title, row.dataset.status)
    );
  });
}

/* ── Modal: detalle de una llamada ───────────────────────────────────── */

function openModal(html) {
  document.getElementById("modal-body").innerHTML = html;
  document.getElementById("modal").hidden = false;
}

function closeModal() {
  document.getElementById("modal").hidden = true;
}

function setupModal() {
  const modal = document.getElementById("modal");
  document.getElementById("modal-close").addEventListener("click", closeModal);
  modal.addEventListener("click", (event) => {
    if (event.target === modal) closeModal();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeModal();
  });
}

async function openCallNotes(callId, title, status) {
  const head = `<h3 class="modal-title">${escapeHtml(title)}</h3>`;
  if (status !== "done") {
    const st = CALL_STATUS[status] || { label: status };
    openModal(
      `${head}<p class="modal-sub">${escapeHtml(st.label)}</p>
       <p class="modal-empty">Enigma todavía está procesando esta llamada. Vuelve en un momento.</p>`
    );
    return;
  }
  openModal(`${head}<p class="modal-sub">cargando notas…</p>`);
  let notes;
  try {
    notes = await getJSON(`/calls/${encodeURIComponent(callId)}/notes`);
  } catch (err) {
    openModal(`${head}<p class="modal-empty">No se pudieron cargar las notas: ${escapeHtml(
      err.message
    )}</p>`);
    return;
  }
  if (!notes.length) {
    openModal(
      `${head}<p class="modal-sub">sin notas</p>
       <p class="modal-empty">Esta llamada no produjo notas atómicas.</p>`
    );
    return;
  }
  const list = notes
    .map((note) => {
      const tags = (note.tags || []).length ? "#" + note.tags.join("  #") : "sin etiquetas";
      return `<div class="modal-note">
        <div class="modal-note-title">${escapeHtml(note.title)}</div>
        <div class="modal-note-meta">${escapeHtml(tags)} · ${escapeHtml(note.status)}</div>
      </div>`;
    })
    .join("");
  openModal(
    `${head}<p class="modal-sub">${notes.length} nota(s) · destiladas por Enigma</p>
     <div class="modal-notes">${list}</div>`
  );
}

/* ── Render de la vista de llamada ───────────────────────────────────── */

function renderCallView() {
  const stage = document.getElementById("call-stage");
  if (!state.call.joined) {
    renderLobby();
    return;
  }
  stage.innerHTML = `
    <div class="call-grid" id="call-grid"></div>
    <div class="call-controls">
      <button class="ctrl" id="ctrl-mic" title="Micrófono">🎙</button>
      <button class="ctrl" id="ctrl-cam" title="Cámara">🎥</button>
      <button class="ctrl" id="ctrl-screen" title="Compartir pantalla">🖥</button>
      <button class="ctrl rec" id="ctrl-rec" title="Grabar la llamada">⏺</button>
      <button class="ctrl hangup" id="ctrl-leave" title="Colgar">✕</button>
    </div>`;
  document.getElementById("ctrl-mic").addEventListener("click", toggleMic);
  document.getElementById("ctrl-cam").addEventListener("click", toggleCam);
  document.getElementById("ctrl-screen").addEventListener("click", toggleScreen);
  document.getElementById("ctrl-rec").addEventListener("click", toggleRecording);
  document.getElementById("ctrl-leave").addEventListener("click", leaveCall);
  renderControls();
  syncTiles();
}

function renderLobby(error) {
  const others = state.call.roster.size;
  const note = others
    ? `${others} persona(s) ya en la llamada.`
    : "Nadie en la llamada todavía. Sé quien la empiece.";
  document.getElementById("call-stage").innerHTML = `
    <div class="call-lobby">
      <div class="lobby-orb"></div>
      <h3>Sala de llamada</h3>
      <p>${error ? escapeHtml(error) : note}</p>
      <button class="btn-join" id="btn-join">Unirse a la llamada</button>
      <div class="lobby-calls" id="lobby-calls"></div>
    </div>`;
  document.getElementById("btn-join").addEventListener("click", joinCall);
  loadCalls();
}

function renderControls() {
  const mic = document.getElementById("ctrl-mic");
  const cam = document.getElementById("ctrl-cam");
  const screen = document.getElementById("ctrl-screen");
  if (mic) mic.classList.toggle("off", !state.call.micOn);
  if (cam) cam.classList.toggle("off", !state.call.camOn);
  if (screen) screen.classList.toggle("on", !!state.call.screenStream);
  const rec = document.getElementById("ctrl-rec");
  if (rec) rec.classList.toggle("on", state.call.recording);
}

/* Crea/actualiza un tile de vídeo por participante sin recrear los <video>. */
function syncTiles() {
  const grid = document.getElementById("call-grid");
  if (!grid || !state.call.joined) return;

  const wanted = ["local", ...state.call.peers.keys()];
  for (const id of wanted) {
    if (!document.getElementById(`tile-${id}`)) {
      const tile = document.createElement("div");
      tile.className = "tile";
      tile.id = `tile-${id}`;
      const name = id === "local" ? state.me : state.call.names.get(id) || "…";
      tile.innerHTML = `
        <video autoplay playsinline${id === "local" ? " muted" : ""}></video>
        <div class="tile-fallback">${avatarHtml(name)}</div>
        <span class="tile-name"></span>`;
      grid.appendChild(tile);
    }
  }
  for (const tile of [...grid.children]) {
    const id = tile.id.replace("tile-", "");
    if (!wanted.includes(id)) tile.remove();
  }

  // Tile local.
  const localTile = document.getElementById("tile-local");
  if (localTile) {
    const video = localTile.querySelector("video");
    if (!state.call.screenStream && video.srcObject !== state.call.localStream) {
      video.srcObject = state.call.localStream;
    }
    localTile.classList.toggle("cam-off", !state.call.camOn && !state.call.screenStream);
    localTile.querySelector(".tile-name").innerHTML =
      escapeHtml(`${state.me} · tú`) + (state.call.micOn ? "" : ' <span class="mic-off">silencio</span>');
  }

  // Tiles remotos.
  for (const [peerId, entry] of state.call.peers) {
    const tile = document.getElementById(`tile-${peerId}`);
    if (!tile) continue;
    const video = tile.querySelector("video");
    if (entry.stream && video.srcObject !== entry.stream) video.srcObject = entry.stream;
    tile.querySelector(".tile-name").textContent = state.call.names.get(peerId) || "Invitado";
  }
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
setupModal();

// Refresca el estado de las llamadas mientras se mira el lobby de la llamada.
setInterval(() => {
  if (state.view === "call" && !state.call.joined) loadCalls();
}, 6000);
