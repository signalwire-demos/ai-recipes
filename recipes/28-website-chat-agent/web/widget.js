/* Concierge chat widget. Talks to the ChatGateway at CONCIERGE_CHAT.endpoint with a
   publishable key; the gateway returns a signed conversation handle in X-Chat-Handle,
   which is kept in sessionStorage so a reload resumes the conversation. */
(function () {
  "use strict";
  const cfg = window.CONCIERGE_CHAT || {};
  const STORE = "concierge-chat-handle";
  const store = {
    get() { try { return sessionStorage.getItem(STORE); } catch (e) { return null; } },
    set(v) { try { v ? sessionStorage.setItem(STORE, v) : sessionStorage.removeItem(STORE); } catch (e) {} },
  };

  const side = cfg.position === "left" ? "left" : "right";
  const color = cfg.color || "#0b5cad";
  const css = document.createElement("style");
  css.textContent = `
    .cc-bubble { position: fixed; bottom: 20px; ${side}: 20px; width: 56px; height: 56px; border-radius: 50%;
      border: 0; background: ${color}; color: #fff; cursor: pointer; box-shadow: 0 4px 12px rgb(0 0 0 / .2); }
    .cc-panel { position: fixed; bottom: 88px; ${side}: 20px; width: min(360px, calc(100vw - 40px)); height: 460px;
      display: none; flex-direction: column; background: #fff; border-radius: 12px; overflow: hidden;
      box-shadow: 0 8px 28px rgb(0 0 0 / .25); font: 15px/1.4 system-ui, sans-serif; }
    .cc-panel.open { display: flex; }
    .cc-head { background: ${color}; color: #fff; padding: 12px 16px; font-weight: 600; }
    .cc-log { flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 8px; }
    .cc-msg { max-width: 85%; padding: 8px 12px; border-radius: 12px; white-space: pre-wrap; }
    .cc-assistant { background: #eef1f5; align-self: flex-start; }
    .cc-user { background: ${color}; color: #fff; align-self: flex-end; }
    .cc-note { color: #8a94a3; font-size: 13px; align-self: center; }
    .cc-form { display: flex; border-top: 1px solid #e3e7ec; }
    .cc-form input { flex: 1; border: 0; padding: 12px; font: inherit; outline: none; }
    .cc-form button { border: 0; background: none; color: ${color}; font-weight: 600; padding: 0 16px; cursor: pointer; }`;
  document.head.appendChild(css);

  const bubble = Object.assign(document.createElement("button"), { className: "cc-bubble" });
  bubble.innerHTML = '<svg width="26" height="26" viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">' +
    '<path d="M4 4h16a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H9l-5 4v-4a2 2 0 0 1-2-2V6a2 2 0 0 1 2-2z"/></svg>';
  bubble.setAttribute("aria-label", cfg.title || "Chat");
  const panel = document.createElement("section");
  panel.className = "cc-panel";
  panel.innerHTML = '<div class="cc-head"></div><div class="cc-log" aria-live="polite"></div>' +
    '<form class="cc-form"><input name="m" autocomplete="off" placeholder="Type a message" aria-label="Message">' +
    '<button type="submit">Send</button></form>';
  panel.querySelector(".cc-head").textContent = cfg.title || "Chat";
  document.body.append(panel, bubble);
  const log = panel.querySelector(".cc-log");
  const form = panel.querySelector("form");

  function show(role, text) {
    const el = document.createElement("div");
    el.className = "cc-msg cc-" + role;
    el.textContent = text;
    log.appendChild(el);
    log.scrollTop = log.scrollHeight;
    return el;
  }

  async function call(body) {
    const handle = store.get();
    if (handle) body.handle = handle;
    const resp = await fetch(cfg.endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: "Bearer " + cfg.key },
      body: JSON.stringify(body),
    });
    const minted = resp.headers.get("X-Chat-Handle");
    if (minted) store.set(minted);
    const data = JSON.parse(await resp.text()); // a slow turn starts with keepalive whitespace
    if (!resp.ok) throw Object.assign(new Error(data.error || resp.status), { status: resp.status });
    if (data.error) throw new Error(data.error.message || "chat error"); // JSON-RPC error under HTTP 200
    return data;
  }

  async function open() {
    if (log.childElementCount) return;
    if (store.get()) {
      try {
        const { messages } = await call({ method: "log" });
        messages.forEach((m) => show(m.role, m.content));
        if (messages.length) return;
      } catch (e) { store.set(null); } // expired or unknown handle: start over
    }
    const note = show("note", "Connecting...");
    try {
      const { greeting } = await call({ method: "start" });
      note.remove();
      if (greeting) show("assistant", greeting);
    } catch (e) { note.textContent = "Chat is unavailable right now."; }
  }

  bubble.addEventListener("click", () => { panel.classList.toggle("open"); if (panel.classList.contains("open")) open(); });
  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const text = form.m.value.trim();
    if (!text) return;
    form.m.value = "";
    show("user", text);
    const pending = show("note", "...");
    try {
      const data = await call({ message: text });
      pending.remove();
      show("assistant", (data.result && data.result.response) || "(no reply)");
    } catch (e) {
      pending.textContent = e.status === 429 ? "Too many messages. Try again in a minute." : "Message failed. Try again.";
    }
  });
})();
