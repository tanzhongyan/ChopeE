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

  // No deployed backend: config.json is missing or still the example, so the page runs from browser storage.
  function isOfflinePreview(config) {
    return !!(config && config.clientId && config.clientId.startsWith('xxxx'));
  }

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

  const helpers = { formatPrice, escapeHtml, uuid, clampQty, checkoutBody, countdown, isTerminal, isOfflinePreview, authErrorMessage, MAX_QTY };
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

  const stockStore = {
    getAll() {
      try { return JSON.parse(local.get('chopee.stock')) || {}; }
      catch (e) { return {}; }
    },
    get(sku, fallback) {
      const all = this.getAll();
      return all[sku] !== undefined ? all[sku] : fallback;
    },
    decrement(sku, qty) {
      const all = this.getAll();
      const p = state.products.find((x) => x.sku === sku);
      const current = all[sku] !== undefined ? all[sku] : (p && p.stock !== undefined ? p.stock : 20);
      const remaining = Math.max(0, current - qty);
      all[sku] = remaining;
      local.set('chopee.stock', JSON.stringify(all));
      if (p) { p.stock = remaining; p.inStock = remaining > 0; }
      return remaining;
    },
    increment(sku, qty) {
      const all = this.getAll();
      const p = state.products.find((x) => x.sku === sku);
      const current = all[sku] !== undefined ? all[sku] : (p && p.stock !== undefined ? p.stock : 20);
      const updated = current + qty;
      all[sku] = updated;
      local.set('chopee.stock', JSON.stringify(all));
      if (p) { p.stock = updated; p.inStock = updated > 0; }
      return updated;
    }
  };

  const DEFAULT_CATALOG = [
    {"sku": "LIMITED-01", "name": "Limited Edition Sneakers", "price": 19900, "currency": "SGD", "description": "Flash-sale drop, 50 pairs only in Singapore.", "emoji": "👟", "inStock": true, "stock": 50, "category": "FLASH"},
    {"sku": "SKU-01", "name": "Wireless Earbuds", "price": 5900, "currency": "SGD", "description": "Bluetooth 5.3 earbuds with fast wireless charging.", "emoji": "🎧", "inStock": true, "stock": 25, "category": "TECH"},
    {"sku": "SKU-02", "name": "Smartphone Case", "price": 1290, "currency": "SGD", "description": "Shockproof slim clear protective case.", "emoji": "📱", "inStock": true, "stock": 40, "category": "TECH"},
    {"sku": "SKU-03", "name": "Fast Charger 65W", "price": 3500, "currency": "SGD", "description": "USB-C GaN ultra-compact wall charger.", "emoji": "🔌", "inStock": true, "stock": 15, "category": "TECH"},
    {"sku": "SKU-04", "name": "Power Bank 20000mAh", "price": 4500, "currency": "SGD", "description": "Dual USB-C fast portable battery pack.", "emoji": "🔋", "inStock": true, "stock": 20, "category": "TECH"},
    {"sku": "SKU-05", "name": "Mechanical Keyboard", "price": 8900, "currency": "SGD", "description": "Hot-swappable 75% mechanical keyboard.", "emoji": "⌨️", "inStock": true, "stock": 8, "category": "TECH"},
    {"sku": "SKU-06", "name": "Gaming Mouse", "price": 3900, "currency": "SGD", "description": "Ultra-lightweight wireless 16000 DPI mouse.", "emoji": "🖱️", "inStock": true, "stock": 12, "category": "TECH"},
    {"sku": "SKU-07", "name": "Smartwatch", "price": 12900, "currency": "SGD", "description": "Heart-rate, sleep tracking and 7-day battery life.", "emoji": "⌚", "inStock": true, "stock": 10, "category": "TECH"},
    {"sku": "SKU-08", "name": "Bluetooth Speaker", "price": 4900, "currency": "SGD", "description": "IPX7 waterproof 360° portable speaker.", "emoji": "🔊", "inStock": true, "stock": 18, "category": "TECH"},
    {"sku": "SKU-09", "name": "Basic Cotton Tee", "price": 1590, "currency": "SGD", "description": "Premium 100% combed cotton crew-neck t-shirt.", "emoji": "👕", "inStock": true, "stock": 30, "category": "APPAREL"},
    {"sku": "SKU-10", "name": "Denim Jacket", "price": 6900, "currency": "SGD", "description": "Classic washed denim jacket with metal hardware.", "emoji": "🧥", "inStock": true, "stock": 14, "category": "APPAREL"},
    {"sku": "SKU-11", "name": "Slim Fit Jeans", "price": 4900, "currency": "SGD", "description": "Comfort stretch denim with a modern tapered cut.", "emoji": "👖", "inStock": true, "stock": 22, "category": "APPAREL"},
    {"sku": "SKU-12", "name": "Summer Dress", "price": 3900, "currency": "SGD", "description": "Breathable floral midi dress for warm afternoons.", "emoji": "👗", "inStock": true, "stock": 16, "category": "APPAREL"},
    {"sku": "SKU-13", "name": "Running Shoes", "price": 8900, "currency": "SGD", "description": "Breathable responsive mesh trainers.", "emoji": "👟", "inStock": false, "stock": 0, "category": "APPAREL"},
    {"sku": "SKU-14", "name": "Canvas Sneakers", "price": 4500, "currency": "SGD", "description": "Low-top everyday classic canvas sneakers.", "emoji": "👟", "inStock": true, "stock": 25, "category": "APPAREL"},
    {"sku": "SKU-15", "name": "Baseball Cap", "price": 1290, "currency": "SGD", "description": "Adjustable cotton twill vintage cap.", "emoji": "🧢", "inStock": true, "stock": 35, "category": "APPAREL"},
    {"sku": "SKU-16", "name": "Backpack 20L", "price": 5900, "currency": "SGD", "description": "Water-resistant commuter laptop backpack.", "emoji": "🎒", "inStock": true, "stock": 12, "category": "LIFESTYLE"},
    {"sku": "SKU-17", "name": "Sunglasses", "price": 2500, "currency": "SGD", "description": "UV400 polarised classic aviator lenses.", "emoji": "🕶️", "inStock": true, "stock": 20, "category": "LIFESTYLE"},
    {"sku": "SKU-18", "name": "Stainless Water Bottle", "price": 2200, "currency": "SGD", "description": "750 ml double-wall vacuum insulated flask.", "emoji": "🧴", "inStock": true, "stock": 15, "category": "LIFESTYLE"},
    {"sku": "SKU-19", "name": "LED Desk Lamp", "price": 3200, "currency": "SGD", "description": "Touch dimmable eye-care lamp with USB output.", "emoji": "💡", "inStock": true, "stock": 10, "category": "LIFESTYLE"},
    {"sku": "SKU-20", "name": "Yoga Mat", "price": 2800, "currency": "SGD", "description": "6 mm eco-friendly high-density non-slip mat.", "emoji": "🧘", "inStock": true, "stock": 18, "category": "LIFESTYLE"},
    {"sku": "SKU-21", "name": "Skincare Set", "price": 4200, "currency": "SGD", "description": "Gentle hydrating cleanser, toner and moisturiser.", "emoji": "🧴", "inStock": true, "stock": 14, "category": "LIFESTYLE"},
    {"sku": "SKU-22", "name": "Ceramic Mug Set", "price": 1800, "currency": "SGD", "description": "Set of four matte ceramic 350 ml mugs.", "emoji": "☕", "inStock": true, "stock": 24, "category": "LIFESTYLE"},
    {"sku": "SKU-23", "name": "Board Game", "price": 3600, "currency": "SGD", "description": "Family strategy tabletop board game for 2-5 players.", "emoji": "🎲", "inStock": true, "stock": 9, "category": "LIFESTYLE"},
    {"sku": "SKU-24", "name": "Notebook Pack", "price": 1200, "currency": "SGD", "description": "Pack of three A5 dotted grid premium journals.", "emoji": "📓", "inStock": true, "stock": 30, "category": "LIFESTYLE"}
  ];

  const state = {
    config: null, products: [], cart: { items: [], total: 0 }, pendingEmail: null,
    access: store.get('chopee.access'), refresh: store.get('chopee.refresh'), email: store.get('chopee.email'),
    checkoutKey: null, pollTimer: null, tickTimer: null, trackRun: 0,
    activeCategory: 'ALL', searchQuery: '', sortMode: 'featured'
  };
  let guestId = local.get('chopee.guest');
  // F2-A: eagerly assign a guestId so X-Guest-Id is sent from the very first cart request
  if (!guestId && !state.access) { guestId = uuid(); local.set('chopee.guest', guestId); }

  function banner(msg, isError) {
    const b = $('banner');
    if (!b) return;
    b.textContent = msg || '';
    b.className = 'banner' + (isError ? ' error' : '');
    b.hidden = !msg;
  }

  let toastTimer = null;
  function showToast(msg) {
    const t = $('toast');
    const m = $('toast-message');
    if (!t || !m) return;
    m.textContent = msg || 'Updated cart!';
    t.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { t.hidden = true; }, 3200);
  }

  // ---- API ----
  async function api(method, path, opts) {
    opts = opts || {};
    const headers = { 'Content-Type': 'application/json' };
    if (state.access) headers.Authorization = 'Bearer ' + state.access;
    else if (guestId && path.indexOf('/cart') === 0) headers['X-Guest-Id'] = guestId;
    if (opts.key) headers['Idempotency-Key'] = opts.key;
    try {
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
    } catch (e) {
      return { status: 0, ok: false, data: null, error: e };
    }
  }

  async function cognito(target, payload) {
    if (isOfflinePreview(state.config)) {
      if (target === 'SignUp') return { UserConfirmed: true };
      if (target === 'ConfirmSignUp') return {};
      if (target === 'InitiateAuth') {
        return {
          AuthenticationResult: {
            AccessToken: 'mock-access-' + Date.now(),
            RefreshToken: 'mock-refresh-' + Date.now(),
            ExpiresIn: 3600
          }
        };
      }
    }
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
    stopTimers();
    state.access = state.refresh = state.email = null;
    ['chopee.access', 'chopee.refresh', 'chopee.email'].forEach(store.del);
    renderChrome();
    loadCart();
    banner('Signed out successfully.');
    location.hash = '#shop';
  }

  // ---- rendering ----
  function renderChrome() {
    const signedIn = !!state.access;
    if ($('nav-auth')) $('nav-auth').hidden = signedIn;
    if ($('nav-orders')) $('nav-orders').hidden = !signedIn;
    if ($('btn-signout')) $('btn-signout').hidden = !signedIn;
    if ($('user-chip')) {
      $('user-chip').hidden = !signedIn;
      if ($('user-email-display') && state.email) $('user-email-display').textContent = state.email;
    }
    const count = (state.cart.items || []).reduce((n, i) => n + i.quantity, 0);
    if ($('cart-count')) $('cart-count').textContent = String(count);
  }

  function getCategory(p) {
    if (p.category) return p.category;
    if (p.sku === 'LIMITED-01' || p.sku.startsWith('LIMITED')) return 'FLASH';
    const s = (p.sku || '').toUpperCase();
    const num = parseInt(s.replace(/\D/g, ''), 10) || 0;
    if (num >= 1 && num <= 8) return 'TECH';
    if (num >= 9 && num <= 15) return 'APPAREL';
    return 'LIFESTYLE';
  }

  function renderProducts() {
    const container = $('products');
    if (!container) return;

    let list = state.products.slice();

    // 1. Category Filter
    if (state.activeCategory && state.activeCategory !== 'ALL') {
      list = list.filter((p) => getCategory(p) === state.activeCategory);
    }

    // 2. Search Query Filter
    if (state.searchQuery) {
      const q = state.searchQuery.toLowerCase();
      list = list.filter((p) =>
        (p.name && p.name.toLowerCase().includes(q)) ||
        (p.description && p.description.toLowerCase().includes(q)) ||
        (p.sku && p.sku.toLowerCase().includes(q))
      );
    }

    // 3. Sorting
    if (state.sortMode === 'price-asc') {
      list.sort((a, b) => a.price - b.price);
    } else if (state.sortMode === 'price-desc') {
      list.sort((a, b) => b.price - a.price);
    } else if (state.sortMode === 'name') {
      list.sort((a, b) => a.name.localeCompare(b.name));
    }

    if (!list.length) {
      container.innerHTML = '<div class="loading-state"><p>No products match your search or filter.</p><button class="btn btn-outline" id="btn-reset-filter" style="margin-top:1rem;">Clear Filters</button></div>';
      const resetBtn = $('btn-reset-filter');
      if (resetBtn) resetBtn.onclick = () => {
        state.searchQuery = '';
        state.activeCategory = 'ALL';
        if ($('search-input')) $('search-input').value = '';
        updateCategoryChips();
        renderProducts();
      };
      return;
    }

    const cartMap = {};
    (state.cart.items || []).forEach((i) => { cartMap[i.sku] = i.quantity; });

    container.innerHTML = list.map((p) => {
      const cat = getCategory(p);
      const isFlash = cat === 'FLASH';
      const inCartQty = cartMap[p.sku] || 0;

      let actionHtml;
      if (p.inStock === false) {
        actionHtml = '<button class="btn-soldout" disabled>Sold out</button>';
      } else if (inCartQty > 0) {
        actionHtml = '<div class="card-stepper">' +
          '<button data-qty="' + escapeHtml(p.sku) + '" data-delta="-1" title="Decrease">−</button>' +
          '<span class="stepper-qty">' + inCartQty + ' in cart</span>' +
          '<button data-qty="' + escapeHtml(p.sku) + '" data-delta="1" title="Increase">+</button>' +
          '</div>';
      } else {
        actionHtml = '<button class="btn-add" data-add="' + escapeHtml(p.sku) + '"><span>+</span> Add to cart</button>';
      }

      let stockBadge;
      if (p.stock === 0 || p.inStock === false) {
        stockBadge = '<span class="stock-tag sold-out">Sold out</span>';
      } else if (p.stock === undefined) {
        stockBadge = '<span class="stock-tag in-stock">In stock</span>';
      } else if (p.stock <= 5) {
        stockBadge = '<span class="stock-tag low-stock">🔥 Only ' + p.stock + ' left!</span>';
      } else if (isFlash) {
        stockBadge = '<span class="stock-tag flash">⚡ ' + p.stock + ' pairs left</span>';
      } else {
        stockBadge = '<span class="stock-tag in-stock">' + p.stock + ' in stock</span>';
      }

      return '<article class="product-card" data-sku="' + escapeHtml(p.sku) + '">' +
        '<div class="card-top">' +
          '<span class="category-tag">' + escapeHtml(cat) + '</span>' +
          stockBadge +
        '</div>' +
        '<div class="product-visual">' +
          '<span class="product-emoji">' + escapeHtml(p.emoji || '📦') + '</span>' +
        '</div>' +
        '<div class="product-info">' +
          '<h3 class="product-name">' + escapeHtml(p.name) + '</h3>' +
          '<p class="product-desc">' + escapeHtml(p.description || '') + '</p>' +
          '<div class="product-footer">' +
            '<div class="product-price">' +
              '<span class="currency-symbol">S$</span>' + (p.price / 100).toFixed(2) +
            '</div>' +
            actionHtml +
          '</div>' +
        '</div>' +
      '</article>';
    }).join('');
  }

  function renderCart() {
    const byName = {};
    state.products.forEach((p) => { byName[p.sku] = p; });
    const lines = state.cart.items || [];

    const linesBox = $('cart-lines');
    if (linesBox) {
      linesBox.innerHTML = lines.length ? lines.map((i) => {
        const p = byName[i.sku] || { name: i.sku, emoji: '📦', price: i.price };
        return '<div class="cart-line-item">' +
          '<div class="item-visual">' + escapeHtml(p.emoji || '📦') + '</div>' +
          '<div class="item-details">' +
            '<div class="item-name">' + escapeHtml(p.name) + '</div>' +
            '<div class="item-sku">SKU: ' + escapeHtml(i.sku) + ' • S$' + (i.price / 100).toFixed(2) + ' each</div>' +
          '</div>' +
          '<div class="item-stepper">' +
            '<button data-qty="' + escapeHtml(i.sku) + '" data-delta="-1" title="Decrease">−</button>' +
            '<span>' + i.quantity + '</span>' +
            '<button data-qty="' + escapeHtml(i.sku) + '" data-delta="1" title="Increase">+</button>' +
          '</div>' +
          '<div class="item-price-total">' + formatPrice(i.price * i.quantity, 'SGD') + '</div>' +
        '</div>';
      }).join('') : '<div class="loading-state"><p>Your cart is empty.</p><a href="#shop" class="btn btn-outline" style="margin-top:1rem;">Start Shopping</a></div>';
    }

    const totalCents = state.cart.total || 0;
    const formatted = formatPrice(totalCents, 'SGD');
    if ($('cart-total')) $('cart-total').textContent = formatted;
    if ($('summary-subtotal')) $('summary-subtotal').textContent = formatted;
    if ($('summary-gst')) $('summary-gst').textContent = 'S$' + ((totalCents * 0.09) / 100).toFixed(2);
    if ($('btn-checkout')) $('btn-checkout').disabled = !lines.length;

    renderChrome();
    renderProducts(); // Refresh card inline quantities
  }

  function orderHtml(o) {
    const items = (o.items || []).map((i) => escapeHtml(i.sku) + ' × ' + i.quantity).join(', ');

    let html = '<div style="margin-bottom:1.25rem;">' +
      '<div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:0.5rem;">' +
        '<div>' +
          '<p style="color:#64748b; font-size:0.85rem; margin-bottom:0.2rem;">Order Reference</p>' +
          '<h3 style="font-size:1.15rem; font-weight:800; margin:0;"><code>' + escapeHtml(o.orderId) + '</code></h3>' +
        '</div>' +
        '<span class="status-badge ' + escapeHtml(o.status) + '">' +
          escapeHtml(o.status === 'PENDING_PAYMENT' ? 'Awaiting Payment' : (o.status === 'PAID' ? 'Paid & Confirmed' : (o.status === 'QUEUED' ? 'Processing...' : o.status))) +
        '</span>' +
      '</div>' +
      (o.reason ? '<p style="color:#64748b; font-size:0.85rem; margin-top:0.4rem;">Status reason: ' + escapeHtml(o.reason) + '</p>' : '') +
      '</div>';

    if (items) {
      html += '<div style="background:#f8fafc; border:1px solid #e2e8f0; border-radius:12px; padding:1rem; margin-bottom:1.25rem;">' +
        '<div style="font-weight:700; margin-bottom:0.4rem; color:#0f172a;">Items in this order:</div>' +
        '<div style="color:#475569; font-size:0.9rem; margin-bottom:0.6rem;">' + items + '</div>' +
        '<div style="border-top:1px solid #e2e8f0; padding-top:0.6rem; display:flex; justify-content:space-between; font-weight:800; font-size:1.05rem;">' +
          '<span>Order Total:</span>' +
          '<span style="color:#f95721;">' + formatPrice(o.total || 0, o.currency) + '</span>' +
        '</div>' +
      '</div>';
    }

    if (o.status === 'PENDING_PAYMENT') {
      html += '<div style="background:#fffbeb; border:1px solid #fef3c7; padding:1.5rem; border-radius:14px; margin-bottom:1rem; text-align:center;">' +
        '<p style="color:#b45309; font-weight:700; font-size:1.05rem; margin-bottom:0.35rem;">Your items are reserved!</p>' +
        '<p style="color:#92400e; font-size:0.88rem; margin-bottom:1.1rem;">Please complete payment within <strong id="countdown" style="font-size:1.25rem; color:#b45309; padding:0 0.2rem;">' + countdown(o.expiresAt) + '</strong> or your items are released.</p>' +
        '<div style="display:flex; justify-content:center; gap:0.75rem; flex-wrap:wrap;">' +
          '<button class="btn btn-primary btn-lg" data-pay="succeeded" data-order="' + escapeHtml(o.orderId) + '">💳 Complete Payment</button> ' +
          '<button class="btn btn-outline" data-pay="declined" data-order="' + escapeHtml(o.orderId) + '">Cancel Order</button>' +
        '</div>' +
      '</div>';
    } else if (o.status === 'QUEUED') {
      html += '<div style="background:#eff6ff; border:1px solid #bfdbfe; color:#1e40af; padding:1.5rem; border-radius:14px; text-align:center;">' +
        '<div class="spinner" style="margin-bottom:0.75rem;"></div>' +
        '<p style="font-weight:700; font-size:1rem; margin-bottom:0.25rem;">Placing your order...</p>' +
        '<p style="font-size:0.85rem; color:#3b82f6;">Securing your items in Singapore inventory.</p>' +
      '</div>';
    } else if (o.status === 'PAID') {
      html += '<div style="background:#ecfdf5; border:1px solid #d1fae5; color:#065f46; padding:1.75rem; border-radius:14px; text-align:center;">' +
        '<div style="font-size:2.5rem; margin-bottom:0.4rem;">🎉</div>' +
        '<h3 style="font-size:1.2rem; font-weight:800; margin-bottom:0.35rem; color:#065f46;">Payment Successful!</h3>' +
        '<p style="font-size:0.88rem; color:#047857; margin-bottom:1.25rem;">Thank you for shopping with ChopeE. Your order has been confirmed and is being prepared for delivery.</p>' +
        '<a href="#shop" class="btn btn-primary">Continue Shopping</a>' +
      '</div>';
    } else if (o.status === 'CANCELLED' || o.status === 'REJECTED') {
      html += '<div style="background:#fef2f2; border:1px solid #fecaca; color:#991b1b; padding:1.5rem; border-radius:14px; text-align:center;">' +
        '<div style="font-size:2rem; margin-bottom:0.3rem;">ℹ️</div>' +
        '<h3 style="font-size:1.1rem; font-weight:800; margin-bottom:0.35rem; color:#991b1b;">Order Cancelled</h3>' +
        '<p style="font-size:0.88rem; color:#b91c1c; margin-bottom:1.25rem;">' +
          (o.reason === 'PAYMENT_TIMEOUT' ? 'The payment reservation time expired. Your reserved items have been released.' : 'This order was cancelled and the reserved items have been released.') +
        '</p>' +
        '<a href="#shop" class="btn btn-outline">Back to Shop</a>' +
      '</div>';
    }
    return html;
  }

  function syncProductStocks() {
    const offline = isOfflinePreview(state.config);
    const all = offline ? stockStore.getAll() : {};
    state.products.forEach((p) => {
      if (all[p.sku] !== undefined) {
        p.stock = all[p.sku];
      } else if (offline && p.stock === undefined) {
        p.stock = p.inStock === false ? 0 : 20;
      }
      if (p.stock !== undefined) p.inStock = p.stock > 0;
    });
    const flashItem = state.products.find((p) => p.sku === 'LIMITED-01');
    const heroFlashStock = $('hero-flash-stock');
    if (heroFlashStock && flashItem) {
      const available = flashItem.stock === undefined ? 'In stock' : flashItem.stock + ' pairs only';
      heroFlashStock.textContent = flashItem.inStock ? available : 'SOLD OUT';
    }
  }

  function updateCatalogStats() {
    const total = state.products.length;
    if ($('stat-product-count')) $('stat-product-count').textContent = total > 0 ? (total >= 10 ? total + '+' : String(total)) : '0';
    if ($('count-all')) $('count-all').textContent = String(total);

    const counts = { FLASH: 0, TECH: 0, APPAREL: 0, LIFESTYLE: 0 };
    state.products.forEach((p) => {
      const cat = getCategory(p);
      if (counts[cat] !== undefined) counts[cat]++;
    });

    if ($('count-flash')) $('count-flash').textContent = String(counts.FLASH);
    if ($('count-tech')) $('count-tech').textContent = String(counts.TECH);
    if ($('count-apparel')) $('count-apparel').textContent = String(counts.APPAREL);
    if ($('count-lifestyle')) $('count-lifestyle').textContent = String(counts.LIFESTYLE);
  }

  // ---- actions ----
  async function loadCatalog() {
    const r = await api('GET', '/catalog');
    if (r.ok && Array.isArray(r.data) && r.data.length) {
      state.products = r.data;
    } else {
      state.products = DEFAULT_CATALOG;
    }
    syncProductStocks();
    updateCatalogStats();
    renderProducts();
  }

  function updateLocalCart(sku, qty) {
    const q = clampQty(qty);
    const p = state.products.find((x) => x.sku === sku);
    const price = p ? p.price : 0;
    const items = (state.cart.items || []).filter((i) => i.sku !== sku);
    if (q > 0) items.push({ sku, quantity: q, price });
    const total = items.reduce((sum, i) => sum + i.price * i.quantity, 0);
    state.cart = { items, total };
    local.set('chopee.localCart', JSON.stringify(state.cart));
    renderCart();
  }

  async function loadCart() {
    let localCart = null;
    try { localCart = JSON.parse(local.get('chopee.localCart')); } catch (e) {}

    const r = await api('GET', '/cart');
    if (r.ok && r.data && Array.isArray(r.data.items) && r.data.items.length > 0) {
      state.cart = r.data;
      local.set('chopee.localCart', JSON.stringify(state.cart));
    } else if (localCart && Array.isArray(localCart.items) && localCart.items.length > 0) {
      state.cart = localCart;
    } else if (r.ok && r.data && Array.isArray(r.data.items)) {
      state.cart = r.data;
    } else {
      state.cart = localCart || { items: [], total: 0 };
    }
    renderCart();
  }

  function qtyOf(sku) {
    const l = (state.cart.items || []).find((i) => i.sku === sku);
    return l ? l.quantity : 0;
  }

  let cartQueue = Promise.resolve();
  function changeQty(sku, delta) {
    const product = state.products.find((p) => p.sku === sku);
    if (delta > 0 && product) {
      showToast('Added ' + (product.emoji || '📦') + ' ' + product.name + ' to cart!');
    }
    cartQueue = cartQueue.then(() => setQty(sku, qtyOf(sku) + delta)).catch(() => {});
    return cartQueue;
  }

  async function setQty(sku, qty) {
    if (!state.access && !guestId) { guestId = uuid(); local.set('chopee.guest', guestId); }
    const r = await api('PUT', '/cart/items/' + encodeURIComponent(sku), { body: { quantity: clampQty(qty) } });
    if (r.ok && r.data && Array.isArray(r.data.items)) {
      state.cart = r.data;
      local.set('chopee.localCart', JSON.stringify(state.cart));
      renderCart();
    } else {
      updateLocalCart(sku, qty);
    }
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
    state.trackRun++; // a poll still in flight sees this and gives up
    clearTimeout(state.pollTimer); clearInterval(state.tickTimer);
    state.pollTimer = state.tickTimer = null;
  }

  function renderOrder(order) {
    if ($('order-box')) $('order-box').innerHTML = orderHtml(order);
  }

  function startCountdown(expiresAt) {
    if (state.tickTimer) return;
    state.tickTimer = setInterval(() => {
      const c = $('countdown'); if (c) c.textContent = countdown(expiresAt);
    }, 1000);
  }

  function trackOrder(orderId, startedAt) {
    stopTimers();
    renderOrder({ orderId, status: 'QUEUED' });
    location.hash = '#order';
    if (isOfflinePreview(state.config) && trackLocalOrder(orderId)) return;
    const run = state.trackRun;
    let shown = null;
    const poll = async () => {
      const r = await api('GET', '/orders/' + encodeURIComponent(orderId));
      if (run !== state.trackRun) return;
      if (r.ok) {
        // Re-render only on a change, so a click is never lost to a rebuilt button.
        if (r.data.status !== shown) { shown = r.data.status; renderOrder(r.data); }
        if (isTerminal(r.data.status)) return stopTimers();
        // Keep polling: the worker applies payment and expiry asynchronously.
        if (r.data.status === 'PENDING_PAYMENT') startCountdown(r.data.expiresAt);
      } else if (r.status === 401 || (!shown && (r.status !== 404 || Date.now() - startedAt > 30000))) {
        if ($('order-box')) $('order-box').innerHTML += '<p>We could not find this order yet. <button class="btn btn-outline" data-retry="' + escapeHtml(orderId) + '">Check again</button></p>';
        return;
      }
      state.pollTimer = setTimeout(poll, 1000);
    };
    poll();
  }

  async function checkout() {
    if (!state.access) { banner('Please sign in to check out.'); location.hash = '#auth'; return; }
    if (!state.checkoutKey) state.checkoutKey = uuid();
    const key = state.checkoutKey;
    const r = await api('POST', '/checkout', { key, body: checkoutBody(state.cart) });
    if (r.status === 503) { banner('Busy right now, retrying…', true); setTimeout(checkout, 1000 * (Number(r.headers.get('Retry-After')) || 1)); return; }
    if (r.ok) {
      state.checkoutKey = null; // accepted: the next checkout is a new order
      banner('');
      const lines = (state.cart.items || []).slice();
      for (const l of lines) await api('PUT', '/cart/items/' + encodeURIComponent(l.sku), { body: { quantity: 0 } });
      state.cart = { items: [], total: 0 };
      local.del('chopee.localCart');
      renderCart();
      trackOrder(r.data.orderId, Date.now());
    } else if (isOfflinePreview(state.config)) {
      banner('');
      createLocalOrder();
    } else {
      if (r.status >= 400 && r.status < 500) state.checkoutKey = null; // refused, so nothing was queued
      banner((r.data && r.data.error) || 'Checkout failed. Your cart is unchanged, please try again.', true);
    }
  }

  function setPayButtons(disabled) {
    document.querySelectorAll('[data-pay]').forEach((b) => { b.disabled = disabled; });
  }

  async function pay(orderId, outcome) {
    setPayButtons(true);
    const r = await api('POST', '/demo/pay/' + encodeURIComponent(orderId), { body: { outcome } });
    if (r.ok) { banner(''); return; } // trackOrder is still polling and shows the worker's result
    if (isOfflinePreview(state.config) && settleLocalOrder(orderId, outcome)) { trackOrder(orderId, Date.now()); return; }
    setPayButtons(false);
    banner((r.data && r.data.error) || 'Payment failed, please try again.', true);
  }

  // ---- offline preview: orders and stock live in browser storage ----
  function localOrders() {
    try { return JSON.parse(local.get('chopee.orders')) || []; } catch (e) { return []; }
  }

  function restoreLocalStock(order) {
    (order.items || []).forEach((it) => stockStore.increment(it.sku, it.quantity));
    syncProductStocks();
    renderProducts();
  }

  function trackLocalOrder(orderId) {
    const orders = localOrders();
    const o = orders.find((x) => x.orderId === orderId);
    if (!o) return false;
    renderOrder(o);
    if (o.status === 'PENDING_PAYMENT') {
      state.tickTimer = setInterval(() => {
        if (new Date(o.expiresAt).getTime() - Date.now() > 0) {
          const c = $('countdown'); if (c) c.textContent = countdown(o.expiresAt);
          return;
        }
        o.status = 'CANCELLED';
        o.reason = 'PAYMENT_TIMEOUT';
        restoreLocalStock(o);
        local.set('chopee.orders', JSON.stringify(orders));
        trackOrder(orderId, Date.now());
      }, 1000);
    }
    return true;
  }

  function createLocalOrder() {
    const order = {
      orderId: 'ord_' + uuid().slice(0, 8),
      status: 'PENDING_PAYMENT',
      items: (state.cart.items || []).slice(),
      total: state.cart.total || 0,
      currency: 'SGD',
      createdAt: new Date().toISOString(),
      expiresAt: new Date(Date.now() + 15 * 60 * 1000).toISOString()
    };
    local.set('chopee.orders', JSON.stringify([order].concat(localOrders())));
    order.items.forEach((it) => stockStore.decrement(it.sku, it.quantity));
    syncProductStocks();
    state.cart = { items: [], total: 0 };
    local.del('chopee.localCart');
    renderCart();
    renderProducts();
    state.checkoutKey = null;
    trackOrder(order.orderId, Date.now());
  }

  function settleLocalOrder(orderId, outcome) {
    const orders = localOrders();
    const o = orders.find((x) => x.orderId === orderId);
    if (!o) return false;
    const wasPending = o.status === 'PENDING_PAYMENT';
    o.status = outcome === 'succeeded' ? 'PAID' : 'CANCELLED';
    if (outcome === 'declined' && wasPending) restoreLocalStock(o);
    local.set('chopee.orders', JSON.stringify(orders));
    return true;
  }

  async function loadOrders() {
    const r = await api('GET', '/orders');
    if (!r.ok && !isOfflinePreview(state.config)) { banner('Could not load your orders, please try again.', true); return; }
    const list = r.ok ? r.data : localOrders();
    const box = $('orders-list');
    if (!box) return;
    box.innerHTML = list.length ? list.map((o) =>
      '<div style="display:flex; justify-content:space-between; align-items:center; padding:0.85rem 0; border-bottom:1px solid #f1f5f9;">' +
        '<div>' +
          '<a href="#order" data-open="' + escapeHtml(o.orderId) + '" style="font-weight:700; color:#f95721;"><code>' + escapeHtml(o.orderId.slice(0, 8)) + '</code></a>' +
          '<span class="status-badge ' + escapeHtml(o.status) + '" style="margin-left:0.6rem;">' + escapeHtml(o.status) + '</span>' +
        '</div>' +
        '<span style="font-weight:800; font-size:1rem;">' + formatPrice(o.total || 0, o.currency) + '</span>' +
      '</div>').join('') : '<div class="loading-state"><p>No orders yet. Place a flash order!</p><a href="#shop" class="btn btn-outline" style="margin-top:1rem;">Shop Deals</a></div>';
  }

  // ---- routing and events ----
  const VIEWS = ['shop', 'cart', 'auth', 'order', 'orders'];
  function route() {
    let v = (location.hash || '#shop').slice(1);
    if (VIEWS.indexOf(v) < 0) v = 'shop';
    if ((v === 'orders') && !state.access) v = 'auth';
    VIEWS.forEach((n) => {
      const el = $('view-' + n);
      if (el) el.hidden = n !== v;
      const navEl = $('nav-' + n);
      if (navEl) {
        if (n === v) navEl.classList.add('active');
        else navEl.classList.remove('active');
      }
    });
    if (v === 'orders') loadOrders();
    if (v === 'cart') loadCart();
    if (v === 'shop') renderProducts();
  }

  function updateCategoryChips() {
    const chips = document.querySelectorAll('.chip[data-category]');
    chips.forEach((c) => {
      if (c.dataset.category === state.activeCategory) c.classList.add('active');
      else c.classList.remove('active');
    });
  }

  function wire() {
    root.addEventListener('hashchange', route);
    if ($('btn-signout')) $('btn-signout').addEventListener('click', signOut);
    if ($('btn-checkout')) $('btn-checkout').addEventListener('click', checkout);
    if ($('to-signup')) $('to-signup').addEventListener('click', () => {
      $('form-signin').hidden = true; $('form-signup').hidden = false;
      $('auth-title').textContent = 'Create account';
      if ($('auth-subtitle')) $('auth-subtitle').textContent = 'Register to unlock SQS FIFO instant ordering.';
    });
    if ($('to-signin')) $('to-signin').addEventListener('click', () => {
      $('form-signup').hidden = true; $('form-signin').hidden = false;
      $('auth-title').textContent = 'Sign in';
      if ($('auth-subtitle')) $('auth-subtitle').textContent = 'Sign in to check out and track your flash orders.';
    });

    const guard = (fn) => async (ev) => {
      ev.preventDefault();
      try { await fn(new FormData(ev.target)); } catch (e) { banner(authErrorMessage(e), true); }
    };

    if ($('form-signin')) $('form-signin').addEventListener('submit', guard((f) => signIn(f.get('email'), f.get('password'))));
    if ($('form-signup')) $('form-signup').addEventListener('submit', guard(async (f) => {
      state.pendingEmail = f.get('email'); state.pendingPassword = f.get('password');
      await cognito('SignUp', { Username: state.pendingEmail, Password: state.pendingPassword, UserAttributes: [{ Name: 'email', Value: state.pendingEmail }] });
      $('form-signup').hidden = true; $('form-confirm').hidden = false;
    }));
    if ($('form-confirm')) $('form-confirm').addEventListener('submit', guard(async (f) => {
      await cognito('ConfirmSignUp', { Username: state.pendingEmail, ConfirmationCode: f.get('code').trim() });
      await signIn(state.pendingEmail, state.pendingPassword);
      state.pendingPassword = null; // F3-A: clear credential from memory after use
      state.pendingPassword = null;
    }));

    // Search input listener
    const searchInput = $('search-input');
    if (searchInput) {
      searchInput.addEventListener('input', (ev) => {
        state.searchQuery = ev.target.value.trim();
        renderProducts();
      });
    }

    // Sort select listener
    const sortSelect = $('sort-select');
    if (sortSelect) {
      sortSelect.addEventListener('change', (ev) => {
        state.sortMode = ev.target.value;
        renderProducts();
      });
    }

    // Category chips click listener
    const chipsContainer = $('filter-chips');
    if (chipsContainer) {
      chipsContainer.addEventListener('click', (ev) => {
        const btn = ev.target.closest('.chip[data-category]');
        if (!btn) return;
        state.activeCategory = btn.dataset.category;
        updateCategoryChips();
        renderProducts();
      });
    }


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
    } catch (e) {
      state.config = { apiBase: '/api', region: 'ap-southeast-1', userPoolId: 'local', clientId: 'xxxxxxxxxxxxxxxxxxxxxxxxxx' };
    }
    state.config.apiBase = (state.config.apiBase || '/api').replace(/\/$/, '');
    wire();
    route();
    await Promise.all([loadCatalog(), loadCart()]);
    renderCart();
  }

  start();
})(typeof window !== 'undefined' ? window : globalThis);
