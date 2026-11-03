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
  focus() {}
}
const document = {
  head: new Element('head'), body: new Element('body'),
  currentScript: { dataset: { api: 'https://store.test/wp-json/woo-rag/v1', wpNonce: 'native-nonce' } },
  createElement: tag => new Element(tag), createTextNode: text => ({ textContent: text }),
};
const events = {};
let identity = 'guest', invalidNonce = false, nextConversation = 0;
let pendingRelease, requestSent, pauseNext = false;
const owners = new Map(), requests = [];
const result = (status, data) => ({ ok: status === 200, status, json: async () => data });
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
  if (body.conversation_id && owners.get(body.conversation_id) !== identity) return result(404, {});
  const id = body.conversation_id || String(++nextConversation);
  owners.set(id, identity);
  const response = result(200, { conversation_id: id, reply: 'answer:' + body.message, sources: [] });
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
const form = find(node => node.tag === 'form'), input = find(node => node.tag === 'input');
const submit = async message => { input.value = message; await form.events.submit({ preventDefault() {} }); };
const tick = () => new Promise(resolve => setImmediate(resolve));
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
identity = 'guest';
pendingRelease();
await pending;
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
console.log('PASS: WP widget login, logout, account/session switch, expiry, stale reply; no browser bearer/storage');
