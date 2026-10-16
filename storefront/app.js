/* ChopeE storefront: a no-build single page (plan 06 Section 5.6). Vanilla JS, no CDN, works from file:// with a config.json. */
(function (root) {
  'use strict';

  // ---- pure helpers (unit-tested under node) ----
  const MAX_QTY = 5;

  function formatPrice(cents, currency) {
    return (currency === 'SGD' || !currency ? 'S$' : currency + ' ') + (cents / 100).toFixed(2);
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  }

  function uuid() {
    if (root.crypto && root.crypto.randomUUID) return root.crypto.randomUUID();
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
      const r = Math.floor(Math.random() * 16);
      return (c === 'x' ? r : (r & 3) | 8).toString(16);
    });
  }

  function clampQty(q) { return Math.max(0, Math.min(MAX_QTY, q | 0)); }

  function checkoutBody(cart) {
    return { items: (cart.items || []).map((i) => ({ sku: i.sku, quantity: i.quantity })) };
  }

  function countdown(expiresAt, now) {
    const ms = new Date(expiresAt).getTime() - (now === undefined ? Date.now() : now);
    if (!(ms > 0)) return '0:00';
    const s = Math.ceil(ms / 1000);
    return Math.floor(s / 60) + ':' + String(s % 60).padStart(2, '0');
  }

  const TERMINAL = ['PAID', 'CANCELLED', 'REJECTED'];
  function isTerminal(status) { return TERMINAL.indexOf(status) >= 0; }

  function authErrorMessage(err) {
    const map = {
      UsernameExistsException: 'That email is already registered.',
      UserNotConfirmedException: 'Please confirm your email first.',
      NotAuthorizedException: 'Wrong email or password.',
      CodeMismatchException: 'That code is not right.',
      InvalidPasswordException: 'Password too weak (8+ chars with upper, lower, number and symbol).',
    };
    const type = String((err && (err.__type || err.code)) || '').split('#').pop();
    return map[type] || (err && err.message) || 'Something went wrong.';
  }

  const helpers = { formatPrice, escapeHtml, uuid, clampQty, checkoutBody, countdown, isTerminal, authErrorMessage, MAX_QTY };
  if (typeof module !== 'undefined' && module.exports) { module.exports = helpers; }
  if (typeof document === 'undefined') return;

  // ---- browser app ----
  const $ = (id) => document.getElementById(id);
  const store = {
    get(k) { try { return root.sessionStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { root.sessionStorage.setItem(k, v); } catch (e) { /* tokens stay in memory */ } },
    del(k) { try { root.sessionStorage.removeItem(k); } catch (e) { /* ignore */ } },
  };
  const local = {
    get(k) { try { return root.localStorage.getItem(k); } catch (e) { return null; } },
    set(k, v) { try { root.localStorage.setItem(k, v); } catch (e) { /* ignore */ } },
    del(k) { try { root.localStorage.removeItem(k); } catch (e) { /* ignore */ } },
  };

  const state = {
    config: null, products: [], cart: { items: [], total: 0 }, pendingEmail: null,
    access: store.get('chopee.access'), refresh: store.get('chopee.refresh'), email: store.get('chopee.email'),
    checkoutKey: null, pollTimer: null, tickTimer: null,
  };
  let guestId = local.get('chopee.guest');

  function banner(msg, isError) {
    const b = $('banner');
    b.textContent = msg || '';
    b.className = isError ? 'error' : '';
    b.hidden = !msg;
  }

  // ---- API ----
  async function api(method, path, opts) {
    opts = opts || {};
    const headers = { 'Content-Type': 'application/json' };
    if (state.access) headers.Authorization = 'Bearer ' + state.access;
    else if (guestId && path.indexOf('/cart') === 0) headers['X-Guest-Id'] = guestId;
    if (opts.key) headers['Idempotency-Key'] = opts.key;
    const res = await fetch(state.config.apiBase + path, {
      method, headers, body: opts.body === undefined ? undefined : JSON.stringify(opts.body),
    });
    if (res.status === 401 && state.refresh && !opts.retried) {
      if (await refreshTokens()) return api(method, path, Object.assign({}, opts, { retried: true }));
      signOut();
    }
    let data = null;
    try { data = await res.json(); } catch (e) { /* empty body */ }
    return { status: res.status, ok: res.ok, data, headers: res.headers };
  }

  async function cognito(target, payload) {
    const res = await fetch('https://cognito-idp.' + state.config.region + '.amazonaws.com/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-amz-json-1.1', 'X-Amz-Target': 'AWSCognitoIdentityProviderService.' + target },
      body: JSON.stringify(Object.assign({ ClientId: state.config.clientId }, payload)),
    });
    const data = await res.json();
    if (!res.ok) throw data;
    return data;
  }

  function setSession(result, email) {
    state.access = result.AccessToken;
    if (result.RefreshToken) state.refresh = result.RefreshToken;
    if (email) state.email = email;
    store.set('chopee.access', state.access);
    if (state.refresh) store.set('chopee.refresh', state.refresh);
    if (state.email) store.set('chopee.email', state.email);
  }

  async function refreshTokens() {
    try {
      const d = await cognito('InitiateAuth', { AuthFlow: 'REFRESH_TOKEN_AUTH', AuthParameters: { REFRESH_TOKEN: state.refresh } });
      setSession(d.AuthenticationResult);
      return true;
    } catch (e) { return false; }
  }

  function signOut() {
    state.access = state.refresh = state.email = null;
    ['chopee.access', 'chopee.refresh', 'chopee.email'].forEach(store.del);
    renderChrome();
    loadCart();
    location.hash = '#shop';
  }

  // ---- rendering ----
  function renderChrome() {
    const signedIn = !!state.access;
    $('nav-auth').hidden = signedIn;
    $('nav-orders').hidden = !signedIn;
    $('btn-signout').hidden = !signedIn;
    $('cart-count').textContent = String((state.cart.items || []).reduce((n, i) => n + i.quantity, 0));
  }

  function renderProducts() {
    $('products').innerHTML = state.products.map((p) =>
      '<article class="card"><span class="emoji">' + escapeHtml(p.emoji || '📦') + '</span>' +
      '<strong>' + escapeHtml(p.name) + '</strong><small>' + escapeHtml(p.description || '') + '</small>' +
      '<span class="price">' + formatPrice(p.price, p.currency) + '</span>' +
      (p.inStock === false ? '<button disabled>Sold out</button>'
        : '<button data-add="' + escapeHtml(p.sku) + '">Add to cart</button>') + '</article>').join('') || 'No products yet.';
  }

  function renderCart() {
    const byName = {};
    state.products.forEach((p) => { byName[p.sku] = p; });
    const lines = state.cart.items || [];
    $('cart-lines').innerHTML = lines.length ? lines.map((i) => {
      const p = byName[i.sku] || { name: i.sku, emoji: '📦' };
      return '<div class="line"><span>' + escapeHtml(p.emoji || '') + ' ' + escapeHtml(p.name) + '</span>' +
        '<span><button class="secondary" data-qty="' + escapeHtml(i.sku) + '" data-delta="-1">−</button> ' + i.quantity +
        ' <button class="secondary" data-qty="' + escapeHtml(i.sku) + '" data-delta="1">+</button></span>' +
        '<span>' + formatPrice(i.price * i.quantity, 'SGD') + '</span></div>';
    }).join('') : '<p>Your cart is empty.</p>';
    $('cart-total').textContent = formatPrice(state.cart.total || 0, 'SGD');
    $('btn-checkout').disabled = !lines.length;
    renderChrome();
  }

  function orderHtml(o) {
    const items = (o.items || []).map((i) => escapeHtml(i.sku) + ' × ' + i.quantity).join(', ');
    let html = '<p>Order <code>' + escapeHtml(o.orderId) + '</code></p><p><span class="status ' + escapeHtml(o.status) + '">' +
      escapeHtml(o.status) + '</span>' + (o.reason ? ' (' + escapeHtml(o.reason) + ')' : '') + '</p>';
    if (items) html += '<p>' + items + ' — ' + formatPrice(o.total || 0, o.currency) + '</p>';
    if (o.status === 'PENDING_PAYMENT') {
      html += '<p>Pay within <strong id="countdown">' + countdown(o.expiresAt) + '</strong> or the order is cancelled.</p>' +
        '<button data-pay="succeeded" data-order="' + escapeHtml(o.orderId) + '">Pay (simulated)</button> ' +
        '<button class="secondary" data-pay="declined" data-order="' + escapeHtml(o.orderId) + '">Decline (simulated)</button>';
    } else if (o.status === 'QUEUED') {
      html += '<p>Your order is in the queue…</p>';
    }
    return html;
  }

  // ---- actions ----
  async function loadCatalog() {
    const r = await api('GET', '/catalog');
    if (r.ok) { state.products = r.data; renderProducts(); } else banner('Could not load the catalog.', true);
  }

  async function loadCart() {
    const r = await api('GET', '/cart');
    state.cart = r.ok ? r.data : { items: [], total: 0 };
    renderCart();
  }

  function qtyOf(sku) {
    const l = (state.cart.items || []).find((i) => i.sku === sku);
    return l ? l.quantity : 0;
  }

  // Cart edits run one at a time so rapid clicks each build on the previous response.
  let cartQueue = Promise.resolve();
  function changeQty(sku, delta) {
    cartQueue = cartQueue.then(() => setQty(sku, qtyOf(sku) + delta)).catch(() => {});
    return cartQueue;
  }

  async function setQty(sku, qty) {
    if (!state.access && !guestId) { guestId = uuid(); local.set('chopee.guest', guestId); }
    const r = await api('PUT', '/cart/items/' + encodeURIComponent(sku), { body: { quantity: clampQty(qty) } });
    if (r.ok) { state.cart = r.data; renderCart(); } else banner('Could not update the cart.', true);
  }

  async function mergeGuestCart() {
    if (!guestId) return;
    const r = await api('POST', '/cart/merge', { body: { guestId } });
    if (r.ok) { guestId = null; local.del('chopee.guest'); }
  }

  async function signIn(email, password) {
    const d = await cognito('InitiateAuth', { AuthFlow: 'USER_PASSWORD_AUTH', AuthParameters: { USERNAME: email, PASSWORD: password } });
    setSession(d.AuthenticationResult, email);
    await mergeGuestCart();
    await loadCart();
    banner('Signed in as ' + email);
    location.hash = '#shop';
  }

  function stopTimers() {
    clearTimeout(state.pollTimer); clearInterval(state.tickTimer);
    state.pollTimer = state.tickTimer = null;
  }

  function trackOrder(orderId, startedAt) {
    stopTimers();
    $('order-box').innerHTML = orderHtml({ orderId, status: 'QUEUED' });
    location.hash = '#order';
    const poll = async () => {
      const r = await api('GET', '/orders/' + encodeURIComponent(orderId));
      if (r.ok) {
        $('order-box').innerHTML = orderHtml(r.data);
        if (isTerminal(r.data.status)) { state.checkoutKey = null; return stopTimers(); }
        if (r.data.status === 'PENDING_PAYMENT' && !state.tickTimer) {
          state.tickTimer = setInterval(() => {
            const c = $('countdown'); if (c) c.textContent = countdown(r.data.expiresAt);
          }, 1000);
        }
      } else if (r.status !== 404 || Date.now() - startedAt > 30000) {
        $('order-box').innerHTML += '<p>We could not find this order yet. <button data-retry="' + escapeHtml(orderId) + '">Check again</button></p>';
        return;
      }
      state.pollTimer = setTimeout(poll, 1000);
    };
    poll();
  }

  async function checkout() {
    if (!state.access) { banner('Please sign in to check out.'); location.hash = '#auth'; return; }
    // One key per attempt; a failed attempt reuses it so the server can deduplicate the retry.
    if (!state.checkoutKey) state.checkoutKey = uuid();
    const key = state.checkoutKey;
    const r = await api('POST', '/checkout', { key, body: checkoutBody(state.cart) });
    if (r.status === 503) { banner('Busy right now, retrying…', true); setTimeout(checkout, 1000 * (Number(r.headers.get('Retry-After')) || 1)); return; }
    if (r.status !== 202 && r.status !== 200) { banner('Checkout failed (' + r.status + ').', true); return; }
    banner('');
    const lines = (state.cart.items || []).slice();
    for (const l of lines) await api('PUT', '/cart/items/' + encodeURIComponent(l.sku), { body: { quantity: 0 } });
    state.cart = { items: [], total: 0 }; renderCart();
    trackOrder(r.data.orderId, Date.now());
  }

  async function pay(orderId, outcome) {
    const r = await api('POST', '/demo/pay/' + encodeURIComponent(orderId), { body: { outcome } });
    if (!r.ok) banner('Payment call failed (' + r.status + ').', true);
    else trackOrder(orderId, Date.now());
  }

  async function loadOrders() {
    const r = await api('GET', '/orders');
    const list = r.ok ? r.data : [];
    $('orders-list').innerHTML = list.length ? list.map((o) =>
      '<div class="line"><a href="#order" data-open="' + escapeHtml(o.orderId) + '"><code>' + escapeHtml(o.orderId.slice(0, 8)) +
      '</code></a><span class="status ' + escapeHtml(o.status) + '">' + escapeHtml(o.status) + '</span><span>' +
      formatPrice(o.total || 0, o.currency) + '</span></div>').join('') : '<p>No orders yet.</p>';
  }

  // ---- routing and events ----
  const VIEWS = ['shop', 'cart', 'auth', 'order', 'orders'];
  function route() {
    let v = (location.hash || '#shop').slice(1);
    if (VIEWS.indexOf(v) < 0) v = 'shop';
    if ((v === 'orders') && !state.access) v = 'auth';
    VIEWS.forEach((n) => { $('view-' + n).hidden = n !== v; });
    if (v === 'orders') loadOrders();
    if (v === 'cart') loadCart();
  }

  function wire() {
    root.addEventListener('hashchange', route);
    $('btn-signout').addEventListener('click', signOut);
    $('btn-checkout').addEventListener('click', checkout);
    $('to-signup').addEventListener('click', () => { $('form-signin').hidden = true; $('form-signup').hidden = false; $('auth-title').textContent = 'Create account'; });
    $('to-signin').addEventListener('click', () => { $('form-signup').hidden = true; $('form-signin').hidden = false; $('auth-title').textContent = 'Sign in'; });
    const guard = (fn) => async (ev) => { ev.preventDefault(); try { await fn(new FormData(ev.target)); } catch (e) { banner(authErrorMessage(e), true); } };
    $('form-signin').addEventListener('submit', guard((f) => signIn(f.get('email'), f.get('password'))));
    $('form-signup').addEventListener('submit', guard(async (f) => {
      state.pendingEmail = f.get('email'); state.pendingPassword = f.get('password');
      await cognito('SignUp', { Username: state.pendingEmail, Password: state.pendingPassword, UserAttributes: [{ Name: 'email', Value: state.pendingEmail }] });
      $('form-signup').hidden = true; $('form-confirm').hidden = false;
    }));
    $('form-confirm').addEventListener('submit', guard(async (f) => {
      await cognito('ConfirmSignUp', { Username: state.pendingEmail, ConfirmationCode: f.get('code').trim() });
      await signIn(state.pendingEmail, state.pendingPassword);
      state.pendingPassword = null;
    }));
    document.addEventListener('click', (ev) => {
      const t = ev.target.closest('button,a');
      if (!t) return;
      if (t.dataset.add) changeQty(t.dataset.add, 1);
      else if (t.dataset.qty) changeQty(t.dataset.qty, Number(t.dataset.delta));
      else if (t.dataset.pay) pay(t.dataset.order, t.dataset.pay);
      else if (t.dataset.retry) trackOrder(t.dataset.retry, Date.now());
      else if (t.dataset.open) trackOrder(t.dataset.open, Date.now());
    });
  }

  async function start() {
    try {
      const res = await fetch('config.json', { cache: 'no-store' });
      state.config = await res.json();
    } catch (e) { banner('Missing config.json (apiBase incl. /api, region, userPoolId, clientId).', true); return; }
    state.config.apiBase = (state.config.apiBase || '/api').replace(/\/$/, ''); // includes /api
    wire();
    route();
    await Promise.all([loadCatalog(), loadCart()]);
    renderCart();
  }

  start();
})(typeof window !== 'undefined' ? window : globalThis);
