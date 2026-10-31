/* Drives the real storefront/app.js through order flows with a stub DOM, fake clock and fake API. */
'use strict';
const assert = require('node:assert');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const SOURCE = fs.readFileSync(path.join(__dirname, '../../storefront/app.js'), 'utf8');
const LIVE = { apiBase: '/api', region: 'ap-southeast-1', clientId: 'real-client-id' };
const OFFLINE = { apiBase: '/api', region: 'ap-southeast-1', clientId: 'xxxxxxxx' };
const CART = { items: [{ sku: 'SKU-01', quantity: 1, price: 5900 }], total: 5900 };
const CATALOG = [{ sku: 'LIMITED-01', name: 'Sneakers', price: 19900, currency: 'SGD', inStock: true }];
const EXPIRES_MS = 15 * 60 * 1000;

function memoryStorage(initial) {
  const data = new Map(Object.entries(initial || {}));
  return {
    getItem: (k) => (data.has(k) ? data.get(k) : null),
    setItem: (k, v) => data.set(k, String(v)),
    removeItem: (k) => data.delete(k),
  };
}

function element() {
  let html = '';
  const listeners = {};
  return {
    writes: 0, textContent: '', hidden: false, value: '', dataset: {},
    classList: { add() {}, remove() {} },
    get innerHTML() { return html; },
    set innerHTML(v) { html = v; this.writes++; },
    addEventListener(type, fn) { listeners[type] = fn; },
    fire(type, ev) { return listeners[type](ev); },
    querySelector: () => null,
    querySelectorAll: () => [],
  };
}

async function boot({ config = LIVE, backend, localStore }) {
  const clock = { now: Date.parse('2026-10-31T00:00:00Z'), timers: [], nextId: 1 };
  const elements = new Map();
  const getElement = (id) => { if (!elements.has(id)) elements.set(id, element()); return elements.get(id); };
  const payButtons = [{ disabled: false }, { disabled: false }];
  const requests = [];
  const addTimer = (fn, ms, every) => { clock.timers.push({ id: clock.nextId, at: clock.now + ms, fn, every }); return clock.nextId++; };
  const clearTimer = (id) => { clock.timers = clock.timers.filter((t) => t.id !== id); };
  const documentListeners = {};

  const sandbox = {
    console,
    location: { hash: '' },
    sessionStorage: memoryStorage({ 'chopee.access': 'token' }),
    localStorage: memoryStorage(localStore),
    setTimeout: (fn, ms) => addTimer(fn, ms),
    clearTimeout: clearTimer,
    setInterval: (fn, ms) => addTimer(fn, ms, ms),
    clearInterval: clearTimer,
    addEventListener() {},
    document: {
      getElementById: getElement,
      querySelectorAll: (selector) => (selector === '[data-pay]' ? payButtons : []),
      addEventListener: (type, fn) => { documentListeners[type] = fn; },
    },
    fetch: async (url, init) => {
      if (url === 'config.json') return { json: async () => config };
      const method = (init && init.method) || 'GET';
      const route = url.replace(config.apiBase, '');
      const headers = (init && init.headers) || {};
      requests.push({ method, route, key: headers['Idempotency-Key'] });
      const [status, body] = backend(method, route) || [404, { error: 'not found' }];
      return { status, ok: status < 400, json: async () => body, headers: { get: () => null } };
    },
    __now: () => clock.now,
  };
  sandbox.window = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(`{ const Real = Date;
    globalThis.Date = class extends Real {
      constructor(...a) { if (a.length) super(...a); else super(__now()); }
      static now() { return __now(); }
    }; }`, sandbox);
  vm.runInContext(SOURCE, sandbox);

  const flush = async () => { for (let i = 0; i < 6; i++) await new Promise((r) => setImmediate(r)); };
  const page = {
    sandbox, requests, payButtons, getElement, flush,
    orderHtml: () => getElement('order-box').innerHTML,
    banner: () => getElement('banner').textContent,
    orderPolls: () => requests.filter((r) => r.method === 'GET' && r.route.startsWith('/orders/')).length,
    checkouts: () => requests.filter((r) => r.route === '/checkout'),
    async advance(ms) {
      const end = clock.now + ms;
      for (;;) {
        const due = clock.timers.filter((t) => t.at <= end).sort((a, b) => a.at - b.at)[0];
        if (!due) break;
        clock.now = due.at;
        if (due.every) due.at += due.every; else clearTimer(due.id);
        due.fn();
        await flush();
      }
      clock.now = end;
    },
    async checkout() { await getElement('btn-checkout').fire('click'); await flush(); },
    async pay(outcome) {
      documentListeners.click({ target: { closest: () => ({ dataset: { pay: outcome, order: 'o1' } }) } });
      await flush();
    },
    expiresAt: () => new Date(clock.now + EXPIRES_MS).toISOString(),
  };
  await flush();
  return page;
}

/** Fake checkout and catalog-cart API; set `api.order` to change what GET /orders/{id} returns. */
function fakeApi() {
  const api = {
    order: null,
    checkout: [202, { orderId: 'o1', status: 'QUEUED' }],
    payment: [200, { received: true }],
  };
  api.backend = (method, route) => {
    if (route === '/catalog') return [200, CATALOG];
    if (route === '/cart') return [200, api.checkoutDone ? { items: [], total: 0 } : CART];
    if (route.startsWith('/cart/items/')) return [200, { items: [], total: 0 }];
    if (route === '/checkout') { api.checkoutDone = api.checkout[0] < 400; return api.checkout; }
    if (route.startsWith('/demo/pay/')) return api.payment;
    if (route.startsWith('/orders/')) return api.order ? [200, api.order] : [404, { error: 'order not found' }];
    return null;
  };
  return api;
}

async function placeOrder(page, api) {
  api.order = { orderId: 'o1', status: 'PENDING_PAYMENT', total: 5900, items: CART.items, expiresAt: page.expiresAt() };
  await page.checkout();
  await page.advance(1000);
  assert.match(page.orderHtml(), /data-pay="succeeded"/);
}

test('paid order appears after the worker applies it, then polling stops', async () => {
  const api = fakeApi();
  const page = await boot({ backend: api.backend });
  await placeOrder(page, api);
  await page.pay('succeeded');
  await page.advance(3000); // worker has not run yet
  assert.match(page.orderHtml(), /data-pay/);
  api.order = { ...api.order, status: 'PAID' };
  await page.advance(1000);
  assert.match(page.orderHtml(), /Paid/);
  assert.doesNotMatch(page.orderHtml(), /data-pay/);
  const polls = page.orderPolls();
  await page.advance(10000);
  assert.equal(page.orderPolls(), polls);
});

test('expired order appears as cancelled without a refresh', async () => {
  const api = fakeApi();
  const page = await boot({ backend: api.backend });
  await placeOrder(page, api);
  await page.advance(EXPIRES_MS + 2000); // countdown over, scheduler has not fired yet
  assert.match(page.orderHtml(), /data-pay/);
  api.order = { ...api.order, status: 'CANCELLED', reason: 'PAYMENT_TIMEOUT' };
  await page.advance(1000);
  assert.match(page.orderHtml(), /reservation time expired/);
});

test('an unchanged status does not rebuild the pay buttons', async () => {
  const api = fakeApi();
  const page = await boot({ backend: api.backend });
  await placeOrder(page, api);
  const box = page.getElement('order-box');
  const writes = box.writes;
  await page.advance(5000);
  assert.equal(box.writes, writes);
});

test('a second checkout uses a new key even while the first order is pending', async () => {
  const api = fakeApi();
  const page = await boot({ backend: api.backend });
  await placeOrder(page, api);
  await page.checkout();
  const [first, second] = page.checkouts();
  assert.ok(first.key && second.key);
  assert.notEqual(first.key, second.key);
});

test('accepted checkout removes the saved cart so it cannot come back', async () => {
  const api = fakeApi();
  const page = await boot({ backend: api.backend, localStore: { 'chopee.localCart': JSON.stringify(CART) } });
  await placeOrder(page, api);
  assert.equal(page.sandbox.localStorage.getItem('chopee.localCart'), null);
});

test('503 retries with the same key', async () => {
  const api = fakeApi();
  api.checkout = [503, { error: 'queue unavailable' }];
  const page = await boot({ backend: api.backend });
  await page.checkout();
  await page.advance(1000);
  const [first, second] = page.checkouts();
  assert.equal(first.key, second.key);
});

for (const status of [400, 500]) {
  test(`failed checkout (${status}) shows the error and invents no order`, async () => {
    const api = fakeApi();
    api.checkout = [status, { error: 'backend said no' }];
    const page = await boot({ backend: api.backend, localStore: { 'chopee.localCart': JSON.stringify(CART) } });
    await page.checkout();
    assert.equal(page.banner(), 'backend said no');
    assert.equal(page.sandbox.localStorage.getItem('chopee.orders'), null);
    assert.notEqual(page.sandbox.localStorage.getItem('chopee.localCart'), null);
    assert.notEqual(page.sandbox.location.hash, '#order');
    assert.doesNotMatch(page.orderHtml(), /Awaiting|reserved/);
  });
}

test('failed payment leaves the order pending and allows another try', async () => {
  const api = fakeApi();
  const page = await boot({ backend: api.backend });
  await placeOrder(page, api);
  api.payment = [500, { error: 'payment down' }];
  await page.pay('succeeded');
  assert.equal(page.banner(), 'payment down');
  assert.ok(page.payButtons.every((b) => !b.disabled));
  await page.advance(2000);
  assert.match(page.orderHtml(), /data-pay/);
  assert.doesNotMatch(page.orderHtml(), /Paid/);
});

test('pay buttons are disabled while the payment is being processed', async () => {
  const api = fakeApi();
  const page = await boot({ backend: api.backend });
  await placeOrder(page, api);
  await page.pay('succeeded');
  assert.ok(page.payButtons.every((b) => b.disabled));
});

test('signing out stops order polling', async () => {
  const api = fakeApi();
  const page = await boot({ backend: api.backend });
  await placeOrder(page, api);
  page.getElement('btn-signout').fire('click');
  await page.flush();
  const polls = page.orderPolls();
  await page.advance(10000);
  assert.equal(page.orderPolls(), polls);
});

test('deployed storefront ignores browser stock and invents no count', async () => {
  const api = fakeApi();
  const page = await boot({ backend: api.backend, localStore: { 'chopee.stock': '{"LIMITED-01":3}' } });
  assert.equal(page.getElement('hero-flash-stock').textContent, 'In stock');
});

test('offline preview still works from browser storage', async () => {
  const api = fakeApi();
  api.checkout = [404, null];
  api.payment = [404, null];
  const page = await boot({ config: OFFLINE, backend: api.backend });
  await page.checkout();
  const [order] = JSON.parse(page.sandbox.localStorage.getItem('chopee.orders'));
  assert.equal(order.status, 'PENDING_PAYMENT');
  assert.match(page.orderHtml(), /data-pay/);
  order.orderId = 'o1'; // ids are generated, and pay() in this harness settles o1
  page.sandbox.localStorage.setItem('chopee.orders', JSON.stringify([order]));
  await page.pay('succeeded');
  assert.match(page.orderHtml(), /Paid/);
});
