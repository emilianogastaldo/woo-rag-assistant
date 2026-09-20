// Minimal DOM event harness + real isolated API HTTP. No browser/layout assertion.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import { createHmac } from 'node:crypto';

class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.dataset = {}; this.style = {}; this.events = {}; }
  append(...nodes) { nodes.forEach(node => this.appendChild(node)); }
  appendChild(node) { this.children.push(node); node.parent = this; return node; }
  replaceChildren(...nodes) { this.children = []; this.append(...nodes); }
  setAttribute(key, value) { this[key] = value; }
  addEventListener(key, callback) { this.events[key] = callback; }
  remove() { if (this.parent) this.parent.children = this.parent.children.filter(n => n !== this); }
  focus() {}
}
const document = {
  head: new Element('head'), body: new Element('body'),
  currentScript: { dataset: { api: 'http://api:8000' } },
  createElement: tag => new Element(tag),
  createTextNode: text => ({ textContent: text }),
};
const started = Date.now();
const requests = [];
let cookie = '', expired = false, invalidConversation = false;
let pauseNext = false, release, requestSent;
const nativeFetch = globalThis.fetch;
async function fetch(url, options = {}) {
  const headers = { ...options.headers };
  if (cookie && options.credentials === 'include') headers.Cookie = cookie;
  if (url.endsWith('/chat')) {
    const body = JSON.parse(options.body);
    assert.deepEqual(Object.keys(body).sort(), ['conversation_id', 'message']);
    requests.push({ ...body });
    if (expired) {
      const payload = Buffer.from(JSON.stringify({ sub: 'mario.rossi@example.com', exp: 1 })).toString('base64url');
      const signature = createHmac('sha256', 'synthetic-session').update(Buffer.from(payload, 'base64url')).digest('base64url');
      headers.Authorization = `Bearer ${payload}.${signature}`;
      expired = false;
    }
    if (invalidConversation) {
      options.body = JSON.stringify({ ...body, conversation_id: 'A'.repeat(43) });
      invalidConversation = false;
    }
  }
  const response = await nativeFetch(url, { ...options, headers });
  const setCookie = response.headers.get('set-cookie');
  if (setCookie) cookie = setCookie.split(';')[0];
  if (url.endsWith('/chat') && pauseNext) {
    pauseNext = false;
    requestSent();
    await new Promise(resolve => { release = resolve; });
  }
  return response;
}
vm.runInNewContext(readFileSync('/widget/chat.js', 'utf8'), { document, window: {}, fetch, URL });
const walk = node => [node, ...(node.children || []).flatMap(walk)];
const find = predicate => walk(document.body).find(predicate);
const button = label => find(n => n.tag === 'button' && n.textContent === label);
const log = find(n => n.className === 'wrag-log');
const input = find(n => n.tag === 'input');
const form = find(n => n.tag === 'form');
const text = node => [node.textContent || '', ...(node.children || []).map(text)].join('');
const waitFor = async predicate => {
  for (let i = 0; i < 200; i++) {
    if (predicate()) return;
    await new Promise(resolve => setTimeout(resolve, 20));
  }
  assert.fail('UI condition timed out');
};
const submit = message => { input.value = message; return form.events.submit({ preventDefault() {} }); };
const login = async label => {
  button('Accedi come ' + label).events.click();
  await waitFor(() => text(document.body).includes('Sessione: ' + label));
};
await submit('guest-first');
assert.equal(requests.at(-1).conversation_id, null);
await submit('RECALL');
assert.ok(requests.at(-1).conversation_id);
assert.ok(text(log).includes('guest-first'));
await login('Mario');
assert.ok(!text(log).includes('guest-first'));
await submit('PRIVATE-MARIO');
assert.equal(requests.at(-1).conversation_id, null);
await login('Luigi');
await submit('RECALL');
assert.equal(requests.at(-1).conversation_id, null);
assert.ok(!text(log).includes('PRIVATE-MARIO'));
assert.ok(text(log).includes('EMPTY'));
button('Continua come ospite').events.click();
await submit('guest-again');
assert.equal(requests.at(-1).conversation_id, null);
// A pending response cannot repopulate the DOM/history after an identity switch.
pauseNext = true;
const sent = new Promise(resolve => { requestSent = resolve; });
const pending = submit('STALE-RESPONSE');
await sent;
await login('Mario');
release();
await pending;
assert.ok(!text(log).includes('STALE-RESPONSE'));
await submit('RECALL');
assert.equal(requests.at(-1).conversation_id, null);
assert.ok(text(log).includes('EMPTY'));
expired = true;
await submit('expire-session');
assert.ok(text(log).includes('Sessione scaduta'));
await submit('after-expired-session');
assert.equal(requests.at(-1).conversation_id, null);
invalidConversation = true;
await submit('expire-conversation');
assert.ok(text(log).includes('Conversazione scaduta'));
await submit('after-expired-conversation');
assert.equal(requests.at(-1).conversation_id, null);
const providerCounts = await (await nativeFetch('http://upstream:9000/admin/counters')).json();
console.log(JSON.stringify({ elapsed_ms: Date.now() - started, local_provider_counts: providerCounts, status: 'PASS', layer: 'DOM + real HTTP', browser_visual: 'NOT RUN',
  checks: ['conversation-contract', 'login', 'logout', 'identity-isolation', 'late-response',
    'expired-session', 'expired-conversation'], chat_requests: requests.length }));
