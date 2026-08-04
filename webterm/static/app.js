/* Multi-session web terminal client.
 *
 * Three things make this feel like an app rather than a demo:
 *
 *  1. one WebSocket for every tab, frames tagged with a session id;
 *  2. every session tracks its absolute byte offset, so a reconnect asks for
 *     exactly what it missed (warm) while a fresh page load asks for a tail of
 *     raw stream and repaints from that (cold);
 *  3. terminals are never destroyed on tab switch, so switching is instant.
 */

const OUTPUT = 1;
const INPUT = 2;
const enc = new TextEncoder();
const dec = new TextDecoder();

function encodeData(kind, sid, offset, payload) {
  const sidBytes = enc.encode(sid);
  const out = new Uint8Array(10 + sidBytes.length + payload.length);
  const view = new DataView(out.buffer);
  view.setUint8(0, kind);
  view.setUint8(1, sidBytes.length);
  view.setBigUint64(2, BigInt(offset));
  out.set(sidBytes, 10);
  out.set(payload, 10 + sidBytes.length);
  return out;
}

function decodeData(buffer) {
  const view = new DataView(buffer);
  const kind = view.getUint8(0);
  const sidLen = view.getUint8(1);
  const offset = Number(view.getBigUint64(2));
  const sid = dec.decode(new Uint8Array(buffer, 10, sidLen));
  return { kind, sid, offset, payload: new Uint8Array(buffer, 10 + sidLen) };
}

const KEYS = {
  esc: "\x1b",
  tab: "\t",
  "shift-tab": "\x1b[Z",
  up: "\x1b[A",
  down: "\x1b[B",
  right: "\x1b[C",
  left: "\x1b[D",
  "ctrl-c": "\x03",
};

const THEME = {
  background: "#101014",
  foreground: "#e6e6ea",
  cursor: "#8b7bf7",
  selectionBackground: "#3a3a52",
  black: "#25252e", red: "#f0707f", green: "#7fd88f", yellow: "#f0c674",
  blue: "#7aa2f7", magenta: "#bb9af7", cyan: "#7dcfff", white: "#c0c0cc",
};

const el = (id) => document.getElementById(id);
const LAST_ACTIVE = "webterm.active";

const app = {
  ws: null,
  wsGen: 0,
  sessions: new Map(), // id -> { meta, term, fit, offset, mount, attachedGen }
  active: null,
  backoff: 400,
  ctrlSticky: false,
  closing: new Set(),
};

/* ---------------------------------------------------------------- sessions */

function makeSession(meta) {
  const term = new Terminal({
    theme: THEME,
    fontFamily:
      'ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, "Liberation Mono", monospace',
    fontSize: window.innerWidth < 640 ? 12 : 13,
    cursorBlink: true,
    scrollback: 5000,
    allowProposedApi: true,
    macOptionIsMeta: true,
  });
  const fit = new FitAddon.FitAddon();
  term.loadAddon(fit);

  const mount = document.createElement("div");
  mount.className = "term";
  mount.dataset.session = meta.id;
  el("terminals").appendChild(mount);
  term.open(mount);

  term.onData((data) => sendInput(meta.id, data));
  term.onBinary((data) => {
    const bytes = new Uint8Array(data.length);
    for (let i = 0; i < data.length; i++) bytes[i] = data.charCodeAt(i) & 255;
    sendRaw(encodeData(INPUT, meta.id, 0, bytes));
  });

  const session = { meta, term, fit, offset: null, mount, attachedGen: null };
  app.sessions.set(meta.id, session);
  return session;
}

function dropSession(id) {
  const session = app.sessions.get(id);
  if (!session) return;
  session.term.dispose();
  session.mount.remove();
  app.sessions.delete(id);
  if (app.active === id) app.active = null;
}

function syncSessionList(list) {
  const seen = new Set();
  for (const meta of list) {
    seen.add(meta.id);
    const existing = app.sessions.get(meta.id);
    if (existing) existing.meta = meta;
    else makeSession(meta);
  }
  for (const id of [...app.sessions.keys()]) if (!seen.has(id)) dropSession(id);

  if (!app.active || !app.sessions.has(app.active)) {
    const remembered = localStorage.getItem(LAST_ACTIVE);
    const pick = app.sessions.has(remembered) ? remembered : [...app.sessions.keys()][0];
    if (pick) selectSession(pick);
  }
  for (const session of app.sessions.values()) attach(session);
  renderTabs();
  el("empty").hidden = app.sessions.size > 0;
}

function selectSession(id) {
  if (!app.sessions.has(id)) return;
  app.active = id;
  localStorage.setItem(LAST_ACTIVE, id);
  for (const [sid, session] of app.sessions) {
    session.mount.classList.toggle("active", sid === id);
  }
  const session = app.sessions.get(id);
  document.title = `${session.meta.name} — web terminal`;
  renderTabs();
  requestAnimationFrame(() => {
    fitActive();
    session.term.focus();
  });
}

/* ------------------------------------------------------------------ socket */

function sendRaw(frame) {
  if (app.ws && app.ws.readyState === WebSocket.OPEN) app.ws.send(frame);
}

function sendCtrl(obj) {
  sendRaw(JSON.stringify(obj));
}

function sendInput(id, data) {
  sendRaw(encodeData(INPUT, id, 0, enc.encode(data)));
}

function attach(session) {
  // Attaching twice on one socket would paint the scrollback twice, and boot()
  // and ws.onopen both legitimately want to attach — so this is idempotent per
  // socket generation. Anything skipped here is picked up by onopen.
  if (!app.ws || app.ws.readyState !== WebSocket.OPEN) return;
  if (session.attachedGen === app.wsGen) return;
  session.attachedGen = app.wsGen;
  // `from: null` means "cold": the server paints us a tail of the raw stream.
  // A number means "warm": send only what we missed after that byte.
  sendCtrl({
    t: "attach",
    session: session.meta.id,
    from: session.offset,
    rows: session.term.rows,
    cols: session.term.cols,
  });
}

function setStatus(state, text) {
  el("status").dataset.state = state;
  el("status-text").textContent = text;
}

function connect() {
  setStatus("connecting", app.backoff > 400 ? "reconnecting" : "connecting");
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  const ws = new WebSocket(`${proto}//${location.host}/ws`);
  ws.binaryType = "arraybuffer";
  app.ws = ws;
  app.wsGen += 1;

  ws.onopen = () => {
    app.backoff = 400;
    setStatus("online", "connected");
    // Re-attach everything we still hold, each from its own offset.
    for (const session of app.sessions.values()) attach(session);
  };

  ws.onmessage = (event) => {
    if (typeof event.data === "string") onControl(JSON.parse(event.data));
    else onOutput(decodeData(event.data));
  };

  ws.onclose = () => {
    setStatus("offline", "reconnecting");
    for (const session of app.sessions.values()) session.attachedGen = null;
    setTimeout(connect, app.backoff);
    app.backoff = Math.min(app.backoff * 2, 8000);
  };

  ws.onerror = () => ws.close();
}

function onOutput({ sid, offset, payload }) {
  const session = app.sessions.get(sid);
  if (!session) return;
  session.term.write(payload);
  session.offset = offset + payload.length;
}

function onControl(msg) {
  const session = msg.session ? app.sessions.get(msg.session) : null;
  switch (msg.t) {
    case "sessions":
      syncSessionList(msg.list);
      break;
    case "attached":
      if (session) {
        if (msg.cold) session.term.reset();
        session.offset = session.offset ?? msg.offset;
      }
      break;
    case "resync":
      // We fell too far behind a flood; the next frame is a fresh tail.
      if (session) session.term.reset();
      break;
    case "gap":
      if (session) {
        session.term.write(
          `\r\n\x1b[2m── ${(msg.resumed_at - msg.from).toLocaleString()} bytes scrolled past while you were away ──\x1b[0m\r\n`,
        );
      }
      break;
    case "exit":
      if (session) {
        session.meta.alive = false;
        session.term.write(`\r\n\x1b[2m── session ended (exit ${msg.exit_code}) ──\x1b[0m\r\n`);
        renderTabs();
      }
      break;
    case "gone":
      if (msg.session) dropSession(msg.session);
      renderTabs();
      break;
  }
}

/* --------------------------------------------------------------------- API */

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "content-type": "application/json" },
    ...options,
  });
  if (!response.ok) throw new Error(`${path}: ${response.status} ${await response.text()}`);
  return response.status === 204 ? null : response.json();
}

async function createSession(command, name) {
  const active = app.sessions.get(app.active);
  const meta = await api("/api/sessions", {
    method: "POST",
    body: JSON.stringify({
      command: command || undefined,
      name: name || undefined,
      rows: active ? active.term.rows : 24,
      cols: active ? active.term.cols : 80,
    }),
  });
  if (!app.sessions.has(meta.id)) makeSession(meta);
  selectSession(meta.id);
  attach(app.sessions.get(meta.id));
  renderTabs();
  el("empty").hidden = true;
}

async function closeSession(id) {
  app.closing.add(id);
  const order = [...app.sessions.keys()];
  const next = order[order.indexOf(id) + 1] || order[order.indexOf(id) - 1];
  try {
    await api(`/api/sessions/${id}`, { method: "DELETE" });
  } finally {
    app.closing.delete(id);
  }
  dropSession(id);
  if (next && app.sessions.has(next)) selectSession(next);
  renderTabs();
  el("empty").hidden = app.sessions.size > 0;
}

/* ----------------------------------------------------------------- chrome */

function renderTabs() {
  const tabs = el("tabs");
  tabs.textContent = "";
  for (const [id, session] of app.sessions) {
    const tab = document.createElement("div");
    tab.className = "tab" + (id === app.active ? " active" : "") + (session.meta.alive === false ? " dead" : "");
    tab.setAttribute("role", "tab");
    tab.dataset.session = id;

    const label = document.createElement("button");
    label.className = "label";
    label.textContent = session.meta.name;
    label.title = `${session.meta.command} — ${session.meta.cwd}`;
    label.onclick = () => selectSession(id);

    const close = document.createElement("button");
    close.className = "close";
    close.textContent = "×";
    close.title = "Close session";
    close.setAttribute("aria-label", `Close ${session.meta.name}`);
    close.onclick = (event) => {
      event.stopPropagation();
      closeSession(id);
    };

    tab.append(label, close);
    tabs.appendChild(tab);
  }
}

function fitActive() {
  const session = app.sessions.get(app.active);
  if (!session) return;
  try {
    session.fit.fit();
  } catch {
    return;
  }
  sendCtrl({ t: "resize", session: session.meta.id, rows: session.term.rows, cols: session.term.cols });
}

async function openPicker() {
  const { profiles } = await api("/api/profiles");
  const list = el("profiles");
  list.textContent = "";
  for (const profile of profiles) {
    const item = document.createElement("li");
    const button = document.createElement("button");
    button.type = "button";
    button.innerHTML = `<span class="kind ${profile.kind}">${profile.kind}</span> ${profile.name}`;
    button.onclick = () => {
      el("picker").close();
      createSession(profile.command, profile.name);
    };
    item.appendChild(button);
    list.appendChild(item);
  }
  el("custom-command").value = "";
  el("picker").showModal();
}

function wireChrome() {
  el("new-tab").onclick = openPicker;
  el("empty-new").onclick = () => createSession(null, null);
  el("picker-go").onclick = () => {
    const command = el("custom-command").value.trim();
    if (command) createSession(command, command.split(/\s+/).slice(0, 2).join(" "));
  };

  for (const button of document.querySelectorAll("#keys button")) {
    button.addEventListener("click", () => {
      const session = app.sessions.get(app.active);
      if (!session) return;
      if (button.dataset.mod === "ctrl") {
        app.ctrlSticky = !app.ctrlSticky;
        button.classList.toggle("on", app.ctrlSticky);
        return;
      }
      sendInput(session.meta.id, KEYS[button.dataset.key] || "");
      session.term.focus();
    });
  }

  // Sticky ctrl for touch: next printable key becomes a control byte.
  document.addEventListener(
    "keydown",
    (event) => {
      if (app.ctrlSticky && event.key.length === 1) {
        event.preventDefault();
        const code = event.key.toUpperCase().charCodeAt(0);
        if (code >= 64 && code < 96) sendInput(app.active, String.fromCharCode(code - 64));
        app.ctrlSticky = false;
        el("mod-ctrl").classList.remove("on");
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "t") {
        event.preventDefault();
        openPicker();
      }
    },
    true,
  );

  let resizeTimer = null;
  const onResize = () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(fitActive, 80);
  };
  window.addEventListener("resize", onResize);
  window.addEventListener("orientationchange", onResize);
  new ResizeObserver(onResize).observe(el("terminals"));

  // Coming back from a locked phone: verify the socket rather than trusting it.
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && app.ws && app.ws.readyState !== WebSocket.OPEN) {
      app.backoff = 400;
      connect();
    }
  });
}

async function boot() {
  wireChrome();
  connect();
  const { sessions } = await api("/api/sessions");
  if (sessions.length === 0) await createSession(null, null);
  else syncSessionList(sessions);
}

boot();
