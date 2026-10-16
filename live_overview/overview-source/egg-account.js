/* Sign-in for the Canon easter egg, the only thing on this page that needs to know who you are.
 *
 * There is no Sign in button: the egg's message (canon-egg.js, shared with the Warm-up
 * Discussion) offers it. Sign-in and the list of finders use the Warm-up Discussion's backend
 * (ISMIR_PUBLIC_CONFIG.loungeOrigin), so both pages share one list. The session is the one
 * lounge.html keeps on this same origin (localStorage), so signing in or out on either page does
 * it on both. Signed in, the header shows your name and Sign out; signed out, nothing at all.
 */
(function () {
  'use strict';
  const origin = String(window.ISMIR_PUBLIC_CONFIG?.loungeOrigin || '').replace(/\/+$/, '');
  if (!/^https?:\/\//.test(origin)) return;   // no backend configured: the egg shows fun facts only

  const TOKEN_KEY = 'pcSession', USER_KEY = 'pcUser';   // shared with lounge.html (api.js, app.js)
  const TOKEN_RE = /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/;
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch (_) { return null; } },
    set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (_) {} },
  };

  // Back from sign-in: the backend hands the session over in the URL fragment (#pc_auth=…), with
  // the page's own fragment, if any, in pc_hash.
  (function takeToken() {
    const params = new URLSearchParams(location.hash.slice(1));
    const token = params.get('pc_auth');
    if (!token && !params.has('pc_link')) return;
    if (TOKEN_RE.test(token || '')) store.set(TOKEN_KEY, token);
    const rest = params.get('pc_hash');
    history.replaceState(null, '', location.pathname + location.search + (rest ? '#' + rest : ''));
  })();

  const apiFetch = (path, opts = {}) => {
    const token = store.get(TOKEN_KEY);
    return fetch(origin + path, { ...opts, headers: { ...(opts.headers || {}), ...(token ? { Authorization: 'Bearer ' + token } : {}) } });
  };
  let user = null;
  try { user = JSON.parse(store.get(USER_KEY) || 'null'); } catch (_) { user = null; }
  if (!store.get(TOKEN_KEY)) user = null;
  let slackApp = null;

  // ---- header: name and Sign out while signed in, nothing otherwise ----
  function render() {
    const slot = document.getElementById('account-slot');
    if (!slot) return;
    slot.replaceChildren();
    slot.hidden = !user;
    if (!user) return;
    const name = document.createElement('span');
    name.className = 'account-name';
    name.textContent = user.name;
    name.title = user.name;
    const out = document.createElement('button');
    out.type = 'button';
    out.className = 'account-signout';
    out.textContent = 'Sign out';
    out.addEventListener('click', () => {
      store.set(TOKEN_KEY, null);
      store.set(USER_KEY, null);
      user = null;
      render();
    });
    slot.append(name, out);
  }

  // ---- signing in (only ever started from the egg's message) ----
  function notice(text, action) {
    document.querySelector('.account-notice')?.remove();
    const box = document.createElement('div');
    box.className = 'account-notice';
    box.setAttribute('role', 'status');
    box.append(document.createTextNode(text + ' '));
    if (action) {
      const a = document.createElement('button');
      a.type = 'button';
      a.textContent = action.label;
      a.addEventListener('click', () => { box.remove(); action.run(); });
      box.append(a);
    }
    document.body.append(box);
    setTimeout(() => box.remove(), 20000);
  }

  function webSignIn() {
    location.href = origin + '/auth/slack/start?return=' + encodeURIComponent(location.href);
  }

  function login() {
    // Phones and tablets with the Slack app: Slack's web sign-in jumps into the app and never
    // comes back, so open our app's Home tab, whose "Enter the Discussion" signs you in (as on
    // lounge.html). This page then picks the session up next time it is opened.
    if (slackApp && matchMedia('(pointer: coarse)').matches) {
      let left = false;
      const onHide = () => { if (document.hidden) left = true; };
      document.addEventListener('visibilitychange', onHide);
      setTimeout(() => {
        document.removeEventListener('visibilitychange', onHide);
        if (left || document.hidden) return;
        const app = window.ISMIR_PUBLIC_CONFIG?.conference?.slackAppName || 'our';
        notice(`Open the ${app} app in Slack and tap “Enter the Discussion”. No Slack app here?`, { label: 'Sign in in the browser', run: webSignIn });
      }, 3000);
      location.href = `slack://app?team=${encodeURIComponent(slackApp.team)}&id=${encodeURIComponent(slackApp.app)}&tab=home`;
      return;
    }
    webSignIn();
  }

  window.PC_EGG = {
    get user() { return user; },
    login,
    solve: () => apiFetch('/api/egg/solve', { method: 'POST' }).then(r => r.json()),
    leaderboard: () => apiFetch('/api/egg/leaderboard', { cache: 'no-store' }).then(r => r.json()),
  };

  async function refresh() {
    try {
      const data = await apiFetch('/api/me', { cache: 'no-store' }).then(r => r.json());
      user = data.user || null;
      slackApp = data.slackApp || null;
      if (!user) store.set(TOKEN_KEY, null);
      store.set(USER_KEY, user ? JSON.stringify(user) : null);
    } catch (_) { /* offline: keep the remembered name */ }
    render();
    window.dispatchEvent(new Event('pc-egg-ready'));   // canon-egg.js may be waiting to record a find
  }

  // Signed in or out on the Warm-up Discussion, or in another tab: follow at once.
  window.addEventListener('storage', (e) => {
    if (e.key !== TOKEN_KEY || (e.oldValue || '') === (e.newValue || '')) return;
    if (!e.newValue) { user = null; render(); return; }
    refresh();
  });

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', render);
  else render();
  refresh();
})();
