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

/** Pick up a session handed back by sign-in, then restore the page's own hash. */
export function takeTokenFromHash() {
  if (!location.hash.startsWith('#pc_auth=')) return;
  const params = new URLSearchParams(location.hash.slice(1));
  const token = params.get('pc_auth') || '';
  if (/^[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+$/.test(token)) writeToken(token);
  const rest = params.get('pc_hash');
  history.replaceState(null, '', location.pathname + location.search + (rest ? '#' + rest : ''));
}

export const clearToken = () => writeToken('');
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
