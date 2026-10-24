(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory;
  else root.ISMIRPublic = factory(root);
})(typeof window === 'undefined' ? globalThis : window, function (env) {
  'use strict';
  const copy = value => JSON.parse(JSON.stringify(value));
  // The organisers' test clock only applies on live-debug.html (features.js sets the channel).
  const testClock = state => env.ISMIRChannel === 'debug' && Boolean(state?.debugClock?.enabled);
  function offline(state, now, snapshot = false) {
    const next = copy(state);
    next.offline = true;
    if (snapshot || !testClock(next)) next.serverNow = new Date(now).toISOString();
    if (snapshot) next.debugClock = { enabled: false, revision: 0 };
    for (const event of next.events || []) {
      for (const item of [event, ...(event.papers || [])]) {
        item.headcounts = { zoom: 0, lobbyZoom: 0, available: false, partial: false };
        if (item.live) item.live = { observerConnected: false, activeSpeakerTalking: false, activeSpeakerName: '', activeSpeakerId: '', recentSpeakers: [] };
        // Join links are only supplied by the live backend, never by stale caches.
        if (item.links) delete item.links.zoom;
        if (snapshot) item.metrics = { available: false };
      }
    }
    return next;
  }
  function mergeLive(state, packet) {
    if (!state || packet.scheduleRevision !== state.scheduleRevision || !Array.isArray(packet.events) || packet.events.length !== state.events.length || !Number.isFinite(Date.parse(packet.serverNow))) return null;
    const next = copy(state), byId = new Map(packet.events.map(e => [e.id, e]));
    if (byId.size !== next.events.length) return null;
    const apply = (target, src) => {
      if (!src || !src.headcounts || !src.metrics || !src.links || !['live','history','upcoming'].includes(src.status)) return false;
      for (const key of ['status','links','headcounts','metrics']) target[key] = copy(src[key]);
      if (src.live) target.live = copy(src.live); else delete target.live;
      return true;
    };
    for (const e of next.events) {
      const item = byId.get(e.id);
      if (!apply(e,item) || !Array.isArray(item.papers) || item.papers.length !== (e.papers || []).length) return null;
      const papers = new Map(item.papers.map(p=>[p.id,p]));
      if (papers.size !== item.papers.length) return null;
      for (const p of e.papers || []) if (!apply(p,papers.get(p.id))) return null;
    }
    for (const key of ['serverNow','updatedAt','version','debugClock']) next[key] = packet[key];
    next.offline = false;
    return next;
  }
  function start({ apiOrigin, fallbackUrl, onState, onStatus }) {
    const origin = new URL(apiOrigin);
    if (origin.origin !== apiOrigin || (origin.protocol !== 'https:' && !['localhost', '127.0.0.1'].includes(origin.hostname))) throw Error('Invalid public API origin');
    const wsUrl = new URL('/ws/public', origin); wsUrl.protocol = origin.protocol === 'https:' ? 'wss:' : 'ws:';
    let stopped = false, socket = null, retry = null, interval, aborter = null;
    let cachedRevision = null;
    let seq = 0, lastState = null, lastFresh = 0, lastWs = 0, lastPoll = -Infinity;
    let pending = false, fallbackPending = false, offlineShown = false, retryMs = 1000;
    const now = () => env.Date.now();   // durations only (freshness, retries)
    // Absolute times: the server's clock (site-integration.js), else this computer's.
    const clockNow = () => (env.ISMIRClock ? env.ISMIRClock.now() : env.Date.now());
    // Each fresh state carries the server's real time (debugClock.realNow; serverNow on older backends).
    const syncClock = (state, localMs) => env.ISMIRClock?.sync(Date.parse(state?.debugClock?.realNow || state?.serverNow), localMs);
    const cacheKey = 'ismir-public-schedule:' + apiOrigin;
    const valid = state => state && Array.isArray(state.events) && state.conference && typeof state.conference === 'object';
    function accept(state, localMs = env.Date.now()) {
      if (stopped || !valid(state)) return;
      syncClock(state, localMs);
      seq++; lastState = copy(state); lastFresh = now(); offlineShown = false;
      onState(lastState); onStatus(true, 'Live updates connected');
      if (cachedRevision !== state.scheduleRevision || cachedRevision === null) {
        try { env.localStorage.setItem(cacheKey, JSON.stringify(offline(lastState, clockNow(), true))); cachedRevision = state.scheduleRevision ?? 0; } catch (_) {}
      }
    }
    async function fallback() {
      if (stopped || lastState || fallbackPending) return;
      fallbackPending = true;
      const controller = new env.AbortController();
      const timeout = env.setTimeout(() => controller.abort(), 5000);
      try {
        let saved;
        try { saved = JSON.parse(env.localStorage.getItem(cacheKey) || 'null'); } catch (_) {}
        if (!valid(saved)) {
          const res = await env.fetch(fallbackUrl, { cache: 'no-store', credentials: 'omit', signal: controller.signal });
          if (!res.ok) throw Error('Snapshot unavailable');
          saved = await res.json();
        }
        if (!stopped && !lastState && valid(saved)) {
          lastState = offline(saved, clockNow(), true); offlineShown = true;
          onState(lastState); onStatus(false, lastState.events.length ? 'Live updates unavailable · saved schedule' : 'Unable to load schedule · reconnecting');
        }
      } catch (_) { if (!stopped && !lastState) onStatus(false, 'Unable to load schedule · reconnecting'); }
      finally { env.clearTimeout(timeout); fallbackPending = false; }
    }
    async function refresh() {
      if (stopped || pending) return;
      pending = true; lastPoll = now(); const at = seq;
      const controller = new env.AbortController(); aborter = controller;
      const timeout = env.setTimeout(() => controller.abort(), 6000);
      try {
        const sent = env.Date.now();
        const res = await env.fetch(new URL('/api/state', origin).href, { cache: 'no-store', credentials: 'omit', signal: controller.signal });
        if (!res.ok) throw Error('State unavailable');
        const received = env.Date.now();   // the server answered about halfway through
        const data = await res.json();
        if (!data.ok || !valid(data.state)) throw Error('Invalid state');
        if (!stopped && at === seq) accept(data.state, (sent + received) / 2);
      } catch (_) { void fallback(); }
      finally { env.clearTimeout(timeout); pending = false; if (aborter === controller) aborter = null; }
    }
    function connect() {
      if (stopped) return;
      env.clearTimeout(retry);
      let candidate;
      try { candidate = new env.WebSocket(wsUrl.href); }
      catch (_) { retry = env.setTimeout(connect, retryMs); retryMs = Math.min(retryMs * 2, 30000); return; }
      socket = candidate; lastWs = now();
      candidate.onmessage = event => {
        if (stopped || socket !== candidate) return;
        try {
          const packet = JSON.parse(event.data);
          if (packet.type === 'state' && valid(packet.state)) { lastWs = now(); retryMs = 1000; accept(packet.state); }
          else if (packet.type === 'live') {
            const merged = mergeLive(lastState, packet);
            if (merged) { lastWs = now(); retryMs = 1000; accept(merged); }
            else void refresh();
          }
        } catch (_) { /* A malformed packet cannot renew freshness. */ }
      };
      candidate.onerror = () => {};
      candidate.onclose = () => {
        if (stopped || socket !== candidate) return;
        socket = null; retry = env.setTimeout(connect, retryMs); retryMs = Math.min(retryMs * 2, 30000);
      };
    }
    function tick() {
      if (stopped) return;
      if (!lastFresh || now() - lastFresh >= 10000) {
        if (lastState && !offlineShown) { offlineShown = true; lastState = offline(lastState, now()); onState(lastState); }
        onStatus(false, lastState?.events.length ? 'Live updates unavailable · reconnecting' : 'Connecting…');
      }
      if (now() - lastPoll >= 5000 && (!lastFresh || now() - lastFresh >= 4500)) void refresh();
      if (socket && now() - lastWs > 15000) {
        const old = socket; socket = null; old.close();
        retry = env.setTimeout(connect, retryMs); retryMs = Math.min(retryMs * 2, 30000);
      }
      // A saved schedule can still cross a session boundary during an outage.
      if (offlineShown && lastState && !testClock(lastState)) {
        lastState.serverNow = new Date(clockNow()).toISOString(); onState(lastState);
      }
    }
    const focus = () => { if (!stopped) { tick(); void refresh(); } };
    env.addEventListener?.('focus', focus);
    env.document?.addEventListener('visibilitychange', focus);
    onStatus(false, 'Connecting…'); void refresh(); connect(); interval = env.setInterval(tick, 1000);
    return { refresh, tick, stop() {
      stopped = true; env.clearInterval(interval); env.clearTimeout(retry); aborter?.abort(); socket?.close();
      env.removeEventListener?.('focus', focus); env.document?.removeEventListener('visibilitychange', focus);
    } };
  }
  return { start, offline, mergeLive };
});
