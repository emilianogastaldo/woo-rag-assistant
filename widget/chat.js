/**
 * Widget chat per woo-rag-assistant.
 *
 * Incorporabile con un solo tag, senza build step:
 *   <script src="/widget/chat.js" data-api="http://localhost:8000"></script>
 *
 * In WordPress usa cookie e nonce nativi: il token backend resta nel proxy PHP.
 * Solo la demo conserva il suo token in memoria, senza storage persistente.
 */
(function () {
  "use strict";

  const script = document.currentScript;
  const API = (script && script.dataset.api) || window.WOO_RAG_API || "http://localhost:8000";
  const TITLE = (script && script.dataset.title || "Assistente del negozio").slice(0, 80);
  const COLOR = script && /^#[0-9a-f]{6}$/i.test(script.dataset.color) ? script.dataset.color : "#315C49";
  const luminance = [1, 3, 5].map(index => parseInt(COLOR.slice(index, index + 2), 16) / 255)
    .map(value => value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4)
    .reduce((sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index], 0);
  const INK = luminance > 0.179 ? "#000" : "#fff";
  const LEFT = script && script.dataset.position === "left";
  const WP_NONCE = script && script.dataset.wpNonce;

  const state = {
    open: false,
    busy: false,
    token: null,
    customerLabel: null,
    conversationId: null,
    epoch: 0,
    wpSessionKey: null,
    wpAuthenticated: false,
  };

  const STYLES = `
  .wrag-launcher,.wrag-panel,.wrag-panel *{box-sizing:border-box}
  .wrag-launcher{position:fixed;right:24px;bottom:calc(20px + env(safe-area-inset-bottom,0px));
    z-index:9998;min-width:88px;min-height:48px;padding:12px 20px;border:1px solid #315C49;
    border-radius:28px;background:#315C49;color:#fff;font:600 15px/1.5 system-ui,sans-serif;
    cursor:pointer;box-shadow:0 6px 24px #18292230}
  .wrag-launcher:hover,.wrag-form button:hover{background:#182922;color:#fff}
  .wrag-panel{position:fixed;right:24px;bottom:calc(84px + env(safe-area-inset-bottom,0px));
    z-index:9999;display:none;flex-direction:column;width:400px;max-width:calc(100vw - 24px);
    height:560px;max-height:calc(100vh - 108px);max-height:calc(100dvh - 108px - env(safe-area-inset-bottom,0px));
    background:#F6F3EC;border:1px solid #315C49;border-radius:16px;overflow:hidden;
    font:14px/1.5 system-ui,sans-serif;color:#182922;box-shadow:0 12px 40px #18292230}
  .wrag-panel[data-open="true"]{display:flex}
  .wrag-head{position:relative;padding:14px 64px 14px 16px;background:#182922;color:#F6F3EC}
  .wrag-head strong{display:block;font-size:16px}
  .wrag-head span{font-size:12px}
  .wrag-panel button,.wrag-panel input{font:inherit;margin:0}
  .wrag-close{position:absolute;right:10px;top:10px;width:44px;height:44px;padding:0;
    border:1px solid #F6F3EC80;border-radius:8px;background:transparent;color:#F6F3EC;
    font-size:24px!important;cursor:pointer}
  .wrag-auth{display:flex;flex-wrap:wrap;gap:8px;padding:8px 12px;border-bottom:1px solid #d4d9cd}
  .wrag-auth button,.wrag-auth a{min-height:44px;padding:10px 8px;font-size:12px;color:#315C49}
  .wrag-auth button{flex:1;cursor:pointer;border:1px solid #315C49;border-radius:6px;background:#fff}
  .wrag-auth button[aria-pressed="true"]{background:#315C49;color:#fff}
  .wrag-panel [hidden]{display:none!important}
  .wrag-log{flex:1;min-height:0;overflow-y:auto;overscroll-behavior:contain;padding:16px;
    display:flex;flex-direction:column;gap:10px}
  .wrag-msg{flex-shrink:0;max-width:90%;padding:10px 12px;border-radius:12px;
    white-space:pre-wrap;overflow-wrap:anywhere}
  .wrag-msg.user{align-self:flex-end;background:#315C49;color:#fff;border-bottom-right-radius:4px}
  .wrag-msg.bot{align-self:flex-start;background:#fff;border:1px solid #d4d9cd;border-bottom-left-radius:4px}
  .wrag-msg.error{align-self:stretch;background:#fff0e9;color:#853e29;border:1px solid #AD593F;font-size:13px}
  .wrag-sources{flex-shrink:0;align-self:flex-start;max-width:100%;font-size:12px;overflow-wrap:anywhere}
  .wrag-panel a{color:#315C49;text-decoration:underline;text-underline-offset:3px}
  .wrag-products{flex-shrink:0;display:grid;gap:10px;max-width:100%}
  .wrag-product{padding:12px;border:1px solid #d4d9cd;border-radius:10px;background:#fff}
  .wrag-product h3{margin:0 0 8px;font-size:14px;overflow-wrap:anywhere}
  .wrag-product p{margin:4px 0;overflow-wrap:anywhere}
  .wrag-product img{display:block;width:80px;height:80px;object-fit:contain;margin-bottom:8px}
  .wrag-product ul{padding-left:20px;margin:8px 0;overflow-wrap:anywhere}
  .wrag-product a{display:inline-block;min-height:44px;padding:10px 0}
  .wrag-msg a{font-weight:600}
  .wrag-status{margin:0;padding:0 16px;font-size:12px;color:#315C49;min-height:24px}
  .wrag-form{display:flex;gap:8px;padding:12px;border-top:1px solid #d4d9cd;background:#fff}
  .wrag-form input{flex:1;min-width:0;min-height:44px;padding:10px;border:1px solid #315C49;
    border-radius:8px;background:#fff;color:#182922;font-size:16px}
  .wrag-form input::placeholder{color:#526358;opacity:1}
  .wrag-form button{min-height:44px;padding:10px 14px;border:1px solid #315C49;border-radius:8px;
    background:#315C49;color:#fff;cursor:pointer}
  .wrag-form button:disabled{background:#526358;cursor:wait}
  .wrag-launcher:focus-visible,.wrag-panel :focus-visible{outline:3px solid #AD593F;outline-offset:3px}
  .wrag-head button:focus-visible{outline-color:#F6F3EC;outline-offset:2px}
  @media(max-width:480px){.wrag-launcher,.wrag-panel{right:12px}.wrag-panel{width:calc(100vw - 24px)}}
  `;

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  const style = el("style");
  style.textContent = STYLES + `
    .wrag-launcher{background:${COLOR};border-color:${COLOR};color:${INK}}
    .wrag-head{background:${COLOR};color:${INK}}
    .wrag-head button{color:${INK};border-color:currentColor}
    ${LEFT ? '.wrag-launcher,.wrag-panel{left:24px;right:auto}@media(max-width:480px){.wrag-launcher,.wrag-panel{left:12px;right:auto}}' : ''}
  `;
  document.head.appendChild(style);

  const launcher = el("button", "wrag-launcher", "Chat");
  launcher.type = "button";
  launcher.setAttribute("aria-label", "Apri la chat di assistenza");
  launcher.setAttribute("aria-expanded", "false");
  launcher.setAttribute("aria-controls", "wrag-panel");

  const panel = el("div", "wrag-panel");
  panel.id = "wrag-panel";
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-labelledby", "wrag-title");
  panel.dataset.open = "false";

  const head = el("div", "wrag-head");
  const title = el("strong", null, TITLE);
  title.id = "wrag-title";
  head.appendChild(title);
  const headNote = el("span", null, "Sessione: ospite");
  head.appendChild(headNote);
  const close = el("button", "wrag-close", "×");
  close.type = "button";
  close.setAttribute("aria-label", "Chiudi la chat di assistenza");
  head.appendChild(close);

  const auth = el("div", "wrag-auth");
  const guestBtn = el("button", null, "Continua come ospite");
  const custABtn = el("button", null, "Accedi come Mario");
  const custBBtn = el("button", null, "Accedi come Luigi");
  const accountLink = el("a", null, "Accedi al negozio");
  const logoutLink = el("a", null, "Esci dal negozio");
  auth.append(guestBtn, custABtn, custBBtn, accountLink, logoutLink);
  accountLink.hidden = logoutLink.hidden = true;
  auth.hidden = true;
  auth.style.display = "none";

  const log = el("div", "wrag-log");
  log.setAttribute("role", "log");
  log.setAttribute("aria-label", "Messaggi della chat");
  log.setAttribute("aria-live", "polite");
  log.setAttribute("aria-relevant", "additions");
  log.tabIndex = 0;
  const status = el("p", "wrag-status", "");
  status.setAttribute("role", "status");

  const form = el("form", "wrag-form");
  const input = el("input");
  input.type = "text";
  input.placeholder = "Scrivi la tua domanda…";
  input.autocomplete = "off";
  input.setAttribute("aria-label", "La tua domanda al negozio");
  const send = el("button", null, "Invia");
  send.type = "submit";
  form.append(input, send);

  panel.append(head, auth, log, status, form);
  document.body.append(launcher, panel);

  function scrollDown() {
    log.scrollTop = log.scrollHeight;
  }

  function safeUrl(value) {
    if (typeof value !== "string" || /[\s\\]/.test(value)) return null;
    let url;
    try { url = new URL(value); } catch (_) { return null; }
    return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url : null;
  }

  function sourceLink(source, label) {
    const url = safeUrl(source.url);
    if (!url) return el("span", null, label);
    const link = el("a", null, label);
    link.href = url.href;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.title = source.title;
    link.setAttribute("aria-label", source.title + " (si apre in una nuova scheda)");
    return link;
  }

  function addMessage(role, text, sources) {
    const node = el("div", "wrag-msg " + role);
    const citations = new Map();
    (sources || []).forEach(function (source, index) {
      (source.chunk_ids || []).forEach(id => citations.set(id, { source, index }));
    });
    let cursor = 0;
    for (const match of text.matchAll(/\[(chunk-v1-[a-f0-9]{64})\]/g)) {
      const citation = citations.get(match[1]);
      if (!citation) continue;
      node.appendChild(document.createTextNode(text.slice(cursor, match.index)));
      node.appendChild(sourceLink(citation.source, "[" + (citation.index + 1) + "]"));
      cursor = match.index + match[0].length;
    }
    node.appendChild(document.createTextNode(text.slice(cursor)));
    log.appendChild(node);
    scrollDown();
  }

  function addSources(sources) {
    if (!sources || !sources.length) return;
    const box = el("div", "wrag-sources");
    box.appendChild(el("span", null, "Fonti: "));
    sources.forEach(function (source, index) {
      if (index) box.appendChild(document.createTextNode(" · "));
      box.appendChild(sourceLink(source, "[" + (index + 1) + "] " + source.title));
    });
    log.appendChild(box);
    scrollDown();
  }

  function productPrice(price, currency) {
    return typeof price === "string" && /^\d+(\.\d+)?$/.test(price) &&
      typeof currency === "string" && /^[A-Z]{3}$/.test(currency)
      ? price + " " + currency : "Prezzo non disponibile";
  }

  function addProducts(products) {
    if (!Array.isArray(products) || !products.length) return;
    const box = el("div", "wrag-products");
    box.setAttribute("role", "list");
    box.setAttribute("aria-label", "Prodotti verificati in questa risposta");
    const stockLabels = { instock: "Disponibile", outofstock: "Esaurito",
      onbackorder: "Ordinabile su prenotazione" };
    products.slice(0, 10).forEach(function (product) {
      if (!product || typeof product.name !== "string" || !Number.isInteger(product.id)) return;
      const card = el("article", "wrag-product");
      card.setAttribute("role", "listitem");
      const title = el("h3");
      title.appendChild(sourceLink({ url: product.url, title: product.name }, product.name));
      const imageUrl = safeUrl(product.image);
      if (imageUrl) {
        const image = el("img");
        image.src = imageUrl.href;
        image.alt = "";
        image.loading = "lazy";
        image.referrerPolicy = "no-referrer";
        image.addEventListener("error", () => { image.hidden = true; });
        card.appendChild(image);
      }
      card.appendChild(title);
      card.appendChild(el("p", null, stockLabels[product.stock_status] || "Disponibilità non verificata"));
      if (product.type === "variable") {
        card.appendChild(el("p", null, "Prezzi delle varianti verificate:"));
        const variants = Array.isArray(product.variants) ? product.variants : [];
        const list = el("ul");
        variants.slice(0, 3).forEach(function (variant) {
          if (!variant || typeof variant !== "object") return;
          const attributes = variant.attributes && typeof variant.attributes === "object"
            ? Object.entries(variant.attributes).map(([name, value]) => name + ": " + value).join(", ")
            : "";
          list.appendChild(el("li", null, (attributes ? attributes + " — " : "") +
            productPrice(variant.price, product.currency) + " · " +
            (stockLabels[variant.stock_status] || "Disponibilità non verificata")));
        });
        card.appendChild(list);
        if (!variants.length) card.appendChild(el("p", null, "Prezzo non disponibile"));
        if (variants.length > 3 || product.variants_may_have_more) {
          card.appendChild(el("p", null, "Altre varianti possono essere disponibili nella scheda."));
        }
      } else card.appendChild(el("p", null, productPrice(product.price, product.currency)));
      if (!safeUrl(product.url)) card.appendChild(el("p", null, "Link alla scheda non disponibile"));
      box.appendChild(card);
    });
    if (box.children.length) log.appendChild(box);
    scrollDown();
  }

  function setSessionLabel() {
    headNote.textContent = state.wpAuthenticated ? "Sessione: account WooCommerce" : state.token
      ? "Sessione: " + state.customerLabel
      : "Sessione: ospite";
    guestBtn.setAttribute("aria-pressed", String(!state.token));
    custABtn.setAttribute("aria-pressed", String(state.customerLabel === "Mario Rossi"));
    custBBtn.setAttribute("aria-pressed", String(state.customerLabel === "Luigi Verdi"));
  }

  function resetConversation(note) {
    state.conversationId = null;
    state.epoch += 1;
    log.replaceChildren();
    addMessage("bot", note);
  }

  async function loadConfig() {
    const response = await fetch(API + "/session/config", {
      credentials: "include",
      headers: WP_NONCE ? { "X-WP-Nonce": WP_NONCE } : {},
      cache: "no-store",
    });
    if (!response.ok) throw new Error("Sessione cambiata: ricarica la pagina e accedi di nuovo.");
    const config = await response.json();
    const wordpress = Boolean(WP_NONCE && config.wordpress);
    auth.hidden = !(wordpress || config.demo_enabled);
    auth.style.display = auth.hidden ? "none" : "flex";
    [guestBtn, custABtn, custBBtn].forEach(button => { button.hidden = !config.demo_enabled; });
    if (wordpress) {
      const changed = state.wpSessionKey !== null && state.wpSessionKey !== config.session_key;
      state.wpSessionKey = config.session_key;
      state.wpAuthenticated = config.authenticated;
      accountLink.hidden = config.authenticated;
      logoutLink.hidden = !config.authenticated;
      accountLink.href = config.login_url;
      logoutLink.href = config.logout_url;
      setSessionLabel();
      if (changed) resetConversation("Sessione cambiata: la conversazione è stata azzerata.");
      return changed;
    }
    return false;
  }

  function expiredSession(message) {
    state.wpSessionKey = null;
    state.wpAuthenticated = false;
    if (WP_NONCE) {
      accountLink.hidden = false;
      logoutLink.hidden = true;
    }
    logout();
    addMessage("error", message);
  }

  async function login(key, label) {
    logout();
    const epoch = state.epoch;
    try {
      const response = await fetch(API + "/demo/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ customer: key }),
      });
      if (!response.ok) throw new Error("login non riuscito");
      const data = await response.json();
      if (epoch !== state.epoch) return;
      state.token = data.token;
      state.customerLabel = label;
      setSessionLabel();
      resetConversation(
        "Bentornato/a " + label + ". Posso controllare i tuoi ordini e le informazioni del negozio."
      );
    } catch (error) {
      if (epoch !== state.epoch) return;
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
    const initialEpoch = state.epoch;
    await configReady;
    if (initialEpoch !== state.epoch) return;
    if (WP_NONCE) {
      try {
        if (await loadConfig()) addMessage("user", message);
      } catch (error) {
        expiredSession(error.message);
        return;
      }
    }
    const epoch = state.epoch;
    const headers = { "Content-Type": "application/json" };
    if (state.token) headers.Authorization = "Bearer " + state.token;
    if (WP_NONCE) headers["X-WP-Nonce"] = WP_NONCE;

    try {
      const response = await fetch(API + "/chat", {
        method: "POST",
        headers: headers,
        credentials: "include",
        body: JSON.stringify({ message: message, conversation_id: state.conversationId }),
      });
      if (epoch !== state.epoch) return;

      if ([401, 403].includes(response.status)) {
        expiredSession("Sessione scaduta: ricarica la pagina e accedi di nuovo.");
        return;
      }
      if ([404, 409].includes(response.status)) {
        resetConversation("Conversazione scaduta o conclusa: invia di nuovo la domanda.");
        return;
      }
      if (response.status === 429) {
        addMessage("error", "Troppe richieste: attendi " +
          (response.headers.get("Retry-After") || "60") + " secondi.");
        return;
      }
      if (!response.ok) throw new Error("HTTP " + response.status);

      const data = await response.json();
      // A login/logout in another tab also hides an answer that was already in flight.
      if (WP_NONCE) {
        try {
          if (await loadConfig()) return;
        } catch (error) {
          expiredSession(error.message);
          return;
        }
      }
      if (epoch !== state.epoch) return;
      state.conversationId = data.conversation_id;
      addMessage("bot", data.reply, data.sources);
      addSources(data.sources);
      addProducts(data.products);
    } catch (error) {
      if (epoch !== state.epoch) return;
      addMessage("error", "L'assistente non è disponibile. Riprova tra poco.");
    }
  }

  function setOpen(open) {
    state.open = open;
    panel.dataset.open = String(state.open);
    launcher.setAttribute("aria-expanded", String(state.open));
    launcher.setAttribute("aria-label", state.open ? "Chiudi la chat di assistenza" : "Apri la chat di assistenza");
    if (state.open) input.focus();
    else launcher.focus();
  }

  launcher.addEventListener("click", function () { setOpen(!state.open); });
  close.addEventListener("click", function () { setOpen(false); });
  panel.addEventListener("keydown", function (event) {
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
    }
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
    form.setAttribute("aria-busy", "true");
    status.textContent = "Sto cercando una risposta…";
    input.value = "";
    addMessage("user", message);
    await ask(message);
    state.busy = false;
    send.disabled = false;
    form.setAttribute("aria-busy", "false");
    status.textContent = "";
    if (state.open && document.activeElement === send) input.focus();
  });

  setSessionLabel();
  logout();
  const configReady = loadConfig().catch(error => {
    if (WP_NONCE) expiredSession(error.message);
  });
  if (WP_NONCE && window.addEventListener) {
    ["focus", "pageshow"].forEach(event => window.addEventListener(event, () => {
      loadConfig().catch(error => expiredSession(error.message));
    }));
  }
})();
