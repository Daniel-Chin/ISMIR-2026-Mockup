// Where the backend lives and how this page authenticates to it.
//
// Served by the Worker itself, PC_CONFIG.apiOrigin is empty and everything is same-origin
// (the HttpOnly session cookie does the work). In the static GitHub Pages build it names the
// Worker; the session then comes back from sign-in in the URL fragment (#pc_auth=…), is kept
// in localStorage, and is sent as a Bearer header or WebSocket subprotocol.

const config = window.PC_CONFIG || {};
export const API = String(config.apiOrigin || '').replace(/\/+$/, '');
const TOKEN_KEY = 'pcSession';

function readToken() { try { return localStorage.getItem(TOKEN_KEY) || ''; } catch { return ''; } }
function writeToken(v) { try { v ? localStorage.setItem(TOKEN_KEY, v) : localStorage.removeItem(TOKEN_KEY); } catch { /* storage blocked */ } }

const TOKEN_RE = /^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/;

/** Expiry (ms) of a signed link token, read from its payload; 0 if unreadable. */
function linkExpiry(t) {
  try { return JSON.parse(atob(t.split('.')[0].replace(/-/g, '+').replace(/_/g, '/'))).exp || 0; } catch { return 0; }
}

/**
 * Pick up a session handed back by sign-in. A Slack-app sign-in also carries its link
 * (pc_link): it stays in the address bar until it expires, so "Open in Safari" from Slack's
 * in-app browser lands here with it, and that browser signs in too (see redeemLink on the
 * Worker). Returns a sign-in URL to follow, or ''.
 */
export function takeTokenFromHash() {
  const params = new URLSearchParams(location.hash.slice(1));
  const token = params.get('pc_auth') || '';
  const link = params.get('pc_link') || '';
  if (!token && !link) return '';
  if (TOKEN_RE.test(token)) writeToken(token);
  const keepLink = TOKEN_RE.test(link) && linkExpiry(link) > Date.now() + 5000;
  const rest = params.get('pc_hash');
  const hash = new URLSearchParams();
  if (keepLink) hash.set('pc_link', link);
  if (rest) hash.set('pc_hash', rest);
  history.replaceState(null, '', location.pathname + location.search + (hash.toString() ? '#' + hash : ''));
  if (keepLink) {
    // Drop the link from the address bar once it can no longer be used.
    setTimeout(() => dropLinkFromUrl(), Math.max(0, linkExpiry(link) - Date.now()));
    // Opened in another browser (no session here yet): redeem the link for this one.
    if (!readToken()) return apiUrl('/auth/slack/link?t=' + encodeURIComponent(link));
  }
  return '';
}

function dropLinkFromUrl() {
  const params = new URLSearchParams(location.hash.slice(1));
  if (!params.has('pc_link')) return;
  const rest = params.get('pc_hash');
  history.replaceState(null, '', location.pathname + location.search + (rest ? '#' + rest : ''));
}

export const clearToken = () => { writeToken(''); dropLinkFromUrl(); };

/**
 * Whether this browser holds a session for this page. The miniconf copy goes only by the shared
 * token (signing out on either site drops it); a cookie the Worker may still send on its own
 * connections must not sign the page back in. The Worker-hosted page uses the cookie itself.
 */
export const hasSession = () => !API || !!readToken();

/**
 * The session is shared with the Live Overview (same origin, same key; its egg-account.js).
 * Signing in or out there, or in another tab, calls `onChange` here.
 */
export function onSessionChange(onChange) {
  window.addEventListener('storage', e => {
    if (e.key === TOKEN_KEY && (e.oldValue || '') !== (e.newValue || '')) onChange();
  });
}
export const apiUrl = path => API + path;

export function apiFetch(path, opts = {}) {
  const token = readToken();
  const headers = { ...(opts.headers || {}) };
  if (token) headers.Authorization = 'Bearer ' + token;
  return fetch(apiUrl(path), { ...opts, headers });
}

export function wsUrl(path) {
  return (API || location.origin).replace(/^http/, 'ws') + path;
}

/** pc.v1 is what the server answers with; the token rides along as a second, unechoed protocol. */
export function wsProtocols() {
  const token = readToken();
  return token ? ['pc.v1', 'pc.auth.' + token] : ['pc.v1'];
}
