/**
 * Widget chat per woo-rag-assistant.
 *
 * Incorporabile con un solo tag, senza build step:
 *   <script src="/widget/chat.js" data-api="http://localhost:8000"></script>
 *
 * Il token di sessione vive solo in memoria e viaggia nell'header Authorization.
 * Il customer ID non è mai noto al client: lo risolve il backend dal token.
 */
(function () {
  "use strict";

  const script = document.currentScript;
  const API = (script && script.dataset.api) || window.WOO_RAG_API || "http://localhost:8000";

  const state = {
    open: false,
    busy: false,
    token: null,
    customerLabel: null,
    history: [],
  };

  const STYLES = `
  .wrag-launcher{position:fixed;right:24px;bottom:24px;z-index:9998;width:56px;height:56px;
    border:0;border-radius:50%;background:#7f54b3;color:#fff;font-size:24px;cursor:pointer;
    box-shadow:0 6px 20px rgba(0,0,0,.25)}
  .wrag-launcher:hover{background:#6b4599}
  .wrag-panel{position:fixed;right:24px;bottom:92px;z-index:9999;display:none;flex-direction:column;
    width:380px;max-width:calc(100vw - 32px);height:560px;max-height:calc(100vh - 140px);
    background:#fff;border-radius:14px;overflow:hidden;font:14px/1.5 system-ui,sans-serif;
    color:#1e1e1e;box-shadow:0 12px 40px rgba(0,0,0,.28)}
  .wrag-panel[data-open="true"]{display:flex}
  .wrag-head{padding:14px 16px;background:#7f54b3;color:#fff}
  .wrag-head strong{display:block;font-size:15px}
  .wrag-head span{font-size:12px;opacity:.85}
  .wrag-auth{display:flex;gap:6px;padding:10px 12px;border-bottom:1px solid #eee;background:#faf9fc}
  .wrag-auth button{flex:1;padding:6px 8px;font-size:12px;cursor:pointer;border:1px solid #d8d1e6;
    border-radius:6px;background:#fff;color:#4a4a4a}
  .wrag-auth button[aria-pressed="true"]{background:#7f54b3;border-color:#7f54b3;color:#fff}
  .wrag-log{flex:1;overflow-y:auto;padding:14px;display:flex;flex-direction:column;gap:10px}
  .wrag-msg{max-width:85%;padding:9px 12px;border-radius:12px;white-space:pre-wrap;word-wrap:break-word}
  .wrag-msg.user{align-self:flex-end;background:#7f54b3;color:#fff;border-bottom-right-radius:4px}
  .wrag-msg.bot{align-self:flex-start;background:#f1f0f5;border-bottom-left-radius:4px}
  .wrag-msg.error{align-self:stretch;background:#fdecea;color:#8b1a10;font-size:13px}
  .wrag-sources{align-self:flex-start;max-width:85%;font-size:12px;color:#666}
  .wrag-sources a{color:#7f54b3}
  .wrag-form{display:flex;gap:8px;padding:12px;border-top:1px solid #eee}
  .wrag-form input{flex:1;padding:9px 11px;border:1px solid #ddd;border-radius:8px;font-size:14px}
  .wrag-form button{padding:9px 14px;border:0;border-radius:8px;background:#7f54b3;color:#fff;
    cursor:pointer}
  .wrag-form button:disabled{opacity:.5;cursor:default}
  .wrag-typing{align-self:flex-start;font-size:12px;color:#888}
  `;

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  const style = el("style");
  style.textContent = STYLES;
  document.head.appendChild(style);

  const launcher = el("button", "wrag-launcher", "💬");
  launcher.setAttribute("aria-label", "Apri la chat di assistenza");

  const panel = el("div", "wrag-panel");
  panel.dataset.open = "false";

  const head = el("div", "wrag-head");
  head.appendChild(el("strong", null, "Assistenza negozio"));
  const headNote = el("span", null, "Sessione: ospite");
  head.appendChild(headNote);

  const auth = el("div", "wrag-auth");
  const guestBtn = el("button", null, "Continua come ospite");
  const custABtn = el("button", null, "Accedi come Mario");
  const custBBtn = el("button", null, "Accedi come Luigi");
  auth.append(guestBtn, custABtn, custBBtn);

  const log = el("div", "wrag-log");

  const form = el("form", "wrag-form");
  const input = el("input");
  input.type = "text";
  input.placeholder = "Scrivi la tua domanda…";
  input.autocomplete = "off";
  const send = el("button", null, "Invia");
  send.type = "submit";
  form.append(input, send);

  panel.append(head, auth, log, form);
  document.body.append(launcher, panel);

  function scrollDown() {
    log.scrollTop = log.scrollHeight;
  }

  function addMessage(role, text) {
    log.appendChild(el("div", "wrag-msg " + role, text));
    scrollDown();
  }

  function addSources(sources) {
    if (!sources || !sources.length) return;
    const box = el("div", "wrag-sources");
    box.appendChild(el("span", null, "Fonti: "));
    sources.forEach(function (source, index) {
      if (index) box.appendChild(document.createTextNode(" · "));
      if (source.url) {
        const link = el("a", null, source.title);
        link.href = source.url;
        link.target = "_blank";
        link.rel = "noopener";
        box.appendChild(link);
      } else {
        box.appendChild(el("span", null, source.title));
      }
    });
    log.appendChild(box);
    scrollDown();
  }

  function setSessionLabel() {
    headNote.textContent = state.token
      ? "Sessione: " + state.customerLabel
      : "Sessione: ospite";
    guestBtn.setAttribute("aria-pressed", String(!state.token));
    custABtn.setAttribute("aria-pressed", String(state.customerLabel === "Mario Rossi"));
    custBBtn.setAttribute("aria-pressed", String(state.customerLabel === "Luigi Verdi"));
  }

  function resetConversation(note) {
    state.history = [];
    log.replaceChildren();
    addMessage("bot", note);
  }

  async function login(key, label) {
    try {
      const response = await fetch(API + "/demo/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ customer: key }),
      });
      if (!response.ok) throw new Error("login non riuscito");
      const data = await response.json();
      state.token = data.token;
      state.customerLabel = label;
      setSessionLabel();
      resetConversation(
        "Bentornato/a " + label + ". Posso controllare i tuoi ordini e le informazioni del negozio."
      );
    } catch (error) {
      addMessage("error", "Login demo non riuscito: " + error.message);
    }
  }

  function logout() {
    state.token = null;
    state.customerLabel = null;
    setSessionLabel();
    resetConversation(
      "Ciao! Posso aiutarti su prodotti, spedizioni e resi. Per lo stato di un ordine serve l'accesso."
    );
  }

  async function ask(message) {
    const typing = el("div", "wrag-typing", "sto cercando…");
    log.appendChild(typing);
    scrollDown();

    const headers = { "Content-Type": "application/json" };
    if (state.token) headers.Authorization = "Bearer " + state.token;

    try {
      const response = await fetch(API + "/chat", {
        method: "POST",
        headers: headers,
        body: JSON.stringify({ message: message, history: state.history }),
      });
      typing.remove();

      if (response.status === 401) {
        state.token = null;
        setSessionLabel();
        addMessage("error", "Sessione scaduta: accedi di nuovo.");
        return;
      }
      if (!response.ok) throw new Error("HTTP " + response.status);

      const data = await response.json();
      addMessage("bot", data.reply);
      addSources(data.sources);
      state.history.push({ role: "user", content: message });
      state.history.push({ role: "assistant", content: data.reply });
    } catch (error) {
      typing.remove();
      addMessage("error", "Non riesco a contattare l'assistente (" + error.message + ").");
    }
  }

  launcher.addEventListener("click", function () {
    state.open = !state.open;
    panel.dataset.open = String(state.open);
    if (state.open) input.focus();
  });

  guestBtn.addEventListener("click", logout);
  custABtn.addEventListener("click", function () {
    login("A", "Mario Rossi");
  });
  custBBtn.addEventListener("click", function () {
    login("B", "Luigi Verdi");
  });

  form.addEventListener("submit", async function (event) {
    event.preventDefault();
    const message = input.value.trim();
    if (!message || state.busy) return;

    state.busy = true;
    send.disabled = true;
    input.value = "";
    addMessage("user", message);
    await ask(message);
    state.busy = false;
    send.disabled = false;
    input.focus();
  });

  setSessionLabel();
  logout();
})();
