// Synthetic DOM and same-origin WP responses; no browser, network or provider.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';

class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.style = {}; this.events = {}; }
  append(...nodes) { nodes.forEach(node => this.appendChild(node)); }
  appendChild(node) { this.children.push(node); node.parent = this; return node; }
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  setAttribute(key, value) { this[key] = value; }
  addEventListener(key, value) { this.events[key] = value; }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(node => node !== this); }
  focus() { document.activeElement = this; }
}
const document = {
  head: new Element('head'), body: new Element('body'),
  currentScript: { dataset: { api: 'https://store.test/wp-json/woo-rag/v1', wpNonce: 'native-nonce' } },
  createElement: tag => new Element(tag), createTextNode: text => ({ textContent: text }),
};
const events = {};
let identity = 'guest', invalidNonce = false, nextConversation = 0;
let pendingRelease, requestSent, pauseNext = false;
let nextStatus = 200, nextSources = [], nextReply, failNext = false;
const owners = new Map(), requests = [];
const result = (status, data) => ({ ok: status === 200, status, json: async () => data,
  headers: { get: name => name === 'Retry-After' ? '7' : null } });
async function fetch(url, options) {
  assert.equal(options.credentials, 'include');
  assert.equal(options.headers['X-WP-Nonce'], 'native-nonce');
  assert.equal(options.headers.Authorization, undefined, 'no browser bearer');
  assert.ok(url.startsWith('https://store.test/wp-json/woo-rag/v1/'));
  if (invalidNonce) return result(403, {});
  if (url.endsWith('/session/config')) return result(200, {
    wordpress: true, demo_enabled: false, authenticated: identity !== 'guest', session_key: identity,
    login_url: 'https://store.test/my-account/', logout_url: 'https://store.test/wp-login.php?action=logout',
  });
  assert.ok(url.endsWith('/chat'));
  const body = JSON.parse(options.body);
  assert.deepEqual(Object.keys(body).sort(), ['conversation_id', 'message']);
  requests.push(body);
  if (failNext) { failNext = false; throw new Error('network unavailable'); }
  if (body.conversation_id && owners.get(body.conversation_id) !== identity) return result(404, {});
  const id = body.conversation_id || String(++nextConversation);
  owners.set(id, identity);
  const response = result(nextStatus, { conversation_id: id, reply: nextReply || 'answer:' + body.message, sources: nextSources });
  nextStatus = 200; nextSources = []; nextReply = undefined;
  if (pauseNext) {
    pauseNext = false;
    requestSent();
    await new Promise(resolve => { pendingRelease = resolve; });
  }
  return response;
}
vm.runInNewContext(readFileSync(new URL('../../widget/chat.js', import.meta.url), 'utf8'), {
  document, window: { addEventListener: (event, callback) => { events[event] = callback; } }, fetch, URL,
});
const walk = node => [node, ...(node.children || []).flatMap(walk)];
const find = predicate => walk(document.body).find(predicate);
const text = node => [node.textContent || '', ...(node.children || []).map(text)].join('');
const log = find(node => node.className === 'wrag-log');
const launcher = find(node => node.className === 'wrag-launcher');
const panel = find(node => node.className === 'wrag-panel');
const close = find(node => node.className === 'wrag-close');
const status = find(node => node.className === 'wrag-status');
const form = find(node => node.tag === 'form'), input = find(node => node.tag === 'input');
const send = find(node => node.type === 'submit');
const submit = async message => { input.value = message; await form.events.submit({ preventDefault() {} }); };
const tick = () => new Promise(resolve => setImmediate(resolve));
assert.equal(launcher['aria-controls'], panel.id);
assert.equal(panel.role, 'dialog');
assert.equal(panel['aria-labelledby'], find(node => node.tag === 'strong').id);
assert.equal(log.role, 'log');
assert.equal(log['aria-live'], 'polite');
assert.equal(log.tabIndex, 0);
assert.ok(input['aria-label']);
assert.equal(status.role, 'status');
launcher.events.click();
assert.equal(launcher['aria-expanded'], 'true');
assert.equal(document.activeElement, input);
let prevented = false;
panel.events.keydown({ key: 'Escape', preventDefault() { prevented = true; } });
assert.ok(prevented);
assert.equal(panel.dataset.open, 'false');
assert.equal(document.activeElement, launcher);
launcher.events.click();
close.events.click();
assert.equal(launcher['aria-expanded'], 'false');
assert.equal(document.activeElement, launcher);
await submit('guest');
await submit('guest-next');
assert.ok(requests.at(-1).conversation_id);
identity = 'native-session-A';
await submit('private-A');
assert.equal(requests.at(-1).conversation_id, null);
assert.ok(!text(log).includes('answer:guest'));
assert.ok(text(document.body).includes('Sessione: account WooCommerce'));
identity = 'native-session-B';
await submit('private-B');
assert.equal(requests.at(-1).conversation_id, null);
assert.ok(!text(log).includes('private-A'));
// A second login for the same Woo account is a distinct native session.
identity = 'native-session-B-second-login';
await submit('new-login');
assert.equal(requests.at(-1).conversation_id, null);
pauseNext = true;
const sent = new Promise(resolve => { requestSent = resolve; });
const pending = submit('late-private');
await sent;
assert.equal(send.disabled, true);
assert.equal(form['aria-busy'], 'true');
assert.ok(text(status).includes('Sto cercando'));
const beforeDuplicate = requests.length;
await submit('duplicate');
assert.equal(requests.length, beforeDuplicate, 'busy blocks a second request');
launcher.events.click();
close.events.click();
identity = 'guest';
pendingRelease();
await pending;
assert.equal(send.disabled, false);
assert.equal(form['aria-busy'], 'false');
assert.equal(text(status), '');
assert.equal(document.activeElement, launcher, 'completion of a closed chat does not steal focus');
assert.ok(!text(log).includes('late-private'), 'discard response after native logout');
assert.ok(text(document.body).includes('Sessione: ospite'));
await submit('new-guest');
assert.equal(requests.at(-1).conversation_id, null);
identity = 'native-session-C';
await submit('private-C');
invalidNonce = true;
const sentBefore = requests.length;
await submit('nonce-expired');
assert.equal(requests.length, sentBefore, 'expired native session stops before chat');
assert.ok(!text(log).includes('private-C'));
assert.ok(text(log).includes('ricarica la pagina'));
invalidNonce = false;
identity = 'guest';
await submit('focus-private');
identity = 'native-session-D';
events.focus();
await tick();
assert.ok(!text(log).includes('focus-private'), 'tab refocus clears old identity');
const chunk = 'chunk-v1-' + 'a'.repeat(64);
nextSources = [
  { title: 'Spedizioni', url: 'https://store.test/spedizioni/', chunk_ids: [chunk] },
  { title: '<script>unsafe</script>', url: 'javascript:alert(1)', chunk_ids: [] },
];
nextReply = 'Consulta [' + chunk + '] <img src=x onerror=alert(1)>';
await submit('sources');
const links = walk(log).filter(node => node.tag === 'a');
assert.equal(links.length, 2, 'inline citation and source list link');
links.forEach(link => {
  assert.equal(link.href, 'https://store.test/spedizioni/');
  assert.equal(link.target, '_blank');
  assert.equal(link.rel, 'noopener noreferrer');
  assert.ok(link['aria-label'].includes('nuova scheda'));
});
assert.ok(text(log).includes('<img src=x onerror=alert(1)>'), 'model markup remains text');
assert.ok(!walk(log).some(node => ['img', 'script'].includes(node.tag)));
for (const statusCode of [404, 409, 429, 503]) {
  nextStatus = statusCode;
  await submit('error-' + statusCode);
  assert.equal(send.disabled, false, 'error releases the composer');
  if ([404, 409].includes(statusCode)) {
    assert.ok(text(log).includes('Conversazione scaduta'));
    await submit('new-conversation');
    assert.equal(requests.at(-1).conversation_id, null);
  } else if (statusCode === 429) assert.ok(text(log).includes('attendi 7 secondi'));
  else assert.ok(text(log).includes('Riprova tra poco'));
}
failNext = true;
await submit('network-error');
assert.ok(text(log).includes('Riprova tra poco'));
assert.equal(send.disabled, false);
nextStatus = 401;
await submit('expired-response');
assert.ok(text(log).includes('Sessione scaduta'));
await submit('after-expired-response');
assert.equal(requests.at(-1).conversation_id, null);
console.log('PASS: WP widget keyboard/focus, live status, safe sources/errors, login/logout/session isolation and stale reply; no browser bearer/storage');
