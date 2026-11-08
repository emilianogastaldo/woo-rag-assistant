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
  currentScript: { dataset: { api: 'https://store.test/wp-json/woo-rag/v1', wpNonce: 'native-nonce', title: '<img onerror=alert(1)>', color: '#ffffff', position: 'left' } },
  createElement: tag => new Element(tag), createTextNode: text => ({ textContent: text }),
};
const events = {};
let identity = 'guest', invalidNonce = false, nextConversation = 0;
let pendingRelease, requestSent, pauseNext = false;
let nextStatus = 200, nextSources = [], nextReply, failNext = false;
let nextProducts;
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
  const data = { conversation_id: id, reply: nextReply || 'answer:' + body.message, sources: nextSources };
  if (nextProducts !== undefined) data.products = nextProducts;
  const response = result(nextStatus, data);
  nextStatus = 200; nextSources = []; nextReply = undefined;
  nextProducts = undefined;
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
assert.equal(find(node => node.tag === 'strong').textContent, '<img onerror=alert(1)>');
assert.ok(document.head.children[0].textContent.includes('color:#000'));
assert.ok(document.head.children[0].textContent.includes('left:24px;right:auto'));
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
nextProducts = [{ id: 8, name: 'private-card', url: 'https://store.test/private', price: '1',
  currency: 'EUR', stock_status: 'instock', type: 'simple' }];
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
assert.ok(!text(log).includes('private-card'), 'discard stale cards after native logout');
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
nextProducts = [
  { id: 1, name: '<svg onload=alert(1)>', url: 'https://store.test/product/1',
    image: 'https://store.test/image.jpg', currency: 'GBP', price: '0',
    stock_status: 'instock', type: 'simple' },
  { id: 2, name: 'Missing data', url: 'javascript:alert(1)', image: 'data:image/svg+xml,<svg/>',
    currency: 'EUR', price: '<img onerror=alert(1)>', stock_status: 'outofstock', type: 'simple' },
  { id: 3, name: 'Variable', url: 'https://store.test/product/3',
    image: 'https://user:password@store.test/private.jpg', currency: 'EUR', price: '999',
    stock_status: 'instock', type: 'variable', variants_may_have_more: true,
    variants: [{ id: 31, price: '49.00', stock_status: 'instock',
      attributes: { '<img src=x>': '<script>unsafe</script>' } }] },
];
await submit('cards');
const productBox = find(node => node.className === 'wrag-products');
assert.equal(productBox.role, 'list');
assert.ok(productBox['aria-label'].includes('Prodotti verificati'));
assert.equal(productBox.children.length, 3);
assert.ok(productBox.children.every(card => card.role === 'listitem'));
const cardLinks = walk(productBox).filter(node => node.tag === 'a');
assert.equal(cardLinks.length, 2, 'invalid URL is not a link');
cardLinks.forEach(link => {
  assert.ok(link.href.startsWith('https://store.test/product/'));
  assert.equal(link.rel, 'noopener noreferrer');
  assert.ok(link['aria-label'].includes('nuova scheda'), 'native links support keyboard navigation');
});
const images = walk(productBox).filter(node => node.tag === 'img');
assert.equal(images.length, 1, 'active schemes and credentials are not images');
assert.equal(images[0].src, 'https://store.test/image.jpg');
assert.equal(images[0].alt, '');
assert.equal(images[0].loading, 'lazy');
assert.equal(images[0].referrerPolicy, 'no-referrer');
images[0].events.error();
assert.equal(images[0].hidden, true, 'broken images are hidden');
assert.ok(text(productBox).includes('<svg onload=alert(1)>'), 'names remain text');
assert.ok(!walk(productBox).some(node => ['script', 'svg'].includes(node.tag)));
assert.ok(text(productBox).includes('0 GBP'), 'zero price and configured currency survive');
assert.ok(text(productBox).includes('Prezzo non disponibile'));
assert.ok(text(productBox).includes('Esaurito'));
assert.ok(text(productBox).includes('49.00 EUR'));
assert.ok(!text(productBox).includes('999'), 'parent price never substitutes for a variation');
assert.ok(text(productBox).includes('Altre varianti'));
identity = 'native-session-card-reset';
events.focus();
await tick();
assert.ok(!find(node => node.className === 'wrag-products'), 'identity change removes cards');
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
console.log('PASS: WP widget keyboard/focus, live status, safe sources/cards/errors, login/logout/session isolation and stale reply; no browser bearer/storage');

for (const dataset of [{ color: 'red;display:none', position: 'bad' }, {}]) {
  const isolated = { ...document, head: new Element('head'), body: new Element('body'), currentScript: { dataset } };
  vm.runInNewContext(readFileSync(new URL('../../widget/chat.js', import.meta.url), 'utf8'), {
    document: isolated, window: { addEventListener() {} }, fetch: async () => result(200, {}), URL,
  });
  assert.ok(!isolated.head.children[0].textContent.includes('red;display:none'));
  assert.ok(!isolated.head.children[0].textContent.includes('left:24px;right:auto'));
  assert.ok(walk(isolated.body).some(node => node.textContent === 'Assistente del negozio'));
}
