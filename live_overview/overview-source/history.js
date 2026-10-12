'use strict';
// Shared with the backend-hosted page: debug-clock and non-publicStatic code paths only run there.
const publicStatic = window.ISMIR_PUBLIC_CONFIG?.staticHosting === true;

const ISMIR_BUILD_VERSION = '1.0.0-ui.6';
window.ISMIR_BUILD_VERSION = ISMIR_BUILD_VERSION;

const root = document.getElementById('history-events-root');
const lastUpdated = document.getElementById('last-updated');
const connection = document.getElementById('connection-status');
const copyHistoryPromptButton = document.getElementById('copy-history-prompt');
const historyCopyStatus = document.getElementById('history-copy-status');
let latestState = null;
let conferenceTimeZone = window.ISMIRSite.timeZone;
let reconnectTimer = null;
let lastClockAuthoritySignature = '';
let clockAuthorityPollBusy = false;
let latestClockRevisionSeen = -1;
function displayTimeZone() {
  return window.ISMIRTimeZone?.getTimeZone?.() || (() => {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || conferenceTimeZone; }
    catch (_) { return conferenceTimeZone; }
  })();
}
const expandedHistoryPaperEventIds = new Set();

const pageParams = new URLSearchParams(location.search);
if (!publicStatic && pageParams.has('debug')) {
  if (pageParams.get('debug') === '0' || pageParams.get('debug') === 'false') localStorage.removeItem('ismir-live-debug');
  else localStorage.setItem('ismir-live-debug', '1');
}
const debugMode = !publicStatic && localStorage.getItem('ismir-live-debug') === '1';

function clockRevision(state) {
  const revision = Number(state?.debugClock?.revision || 0);
  return Number.isFinite(revision) ? Math.max(0, Math.floor(revision)) : 0;
}

function clockAuthoritySignature(state) {
  const clock = state?.debugClock || {};
  return JSON.stringify({
    revision: clockRevision(state),
    enabled: Boolean(clock.enabled),
    baseFakeIso: String(clock.baseFakeIso || ''),
    baseRealIso: String(clock.baseRealIso || ''),
    speed: Number.isFinite(Number(clock.speed)) ? Number(clock.speed) : 1,
  });
}

function debugTimeMs(state) {
  const clock = state?.debugClock || {};
  if (clock.enabled) {
    const baseFake = Date.parse(clock.baseFakeIso || '');
    const baseReal = Date.parse(clock.baseRealIso || '');
    const speed = Number.isFinite(Number(clock.speed)) ? Number(clock.speed) : 1;
    if (Number.isFinite(baseFake) && Number.isFinite(baseReal)) {
      return baseFake + (Date.now() - baseReal) * Math.max(0, Math.min(100, speed));
    }
  }
  const t = Date.parse(state?.serverNow || '');
  return Number.isFinite(t) ? t : Date.now();
}
function isDebugEventVisible(event, state) {
  if (!event?.debugOnly) return true;
  if (!debugMode) return false;
  const now = debugTimeMs(state);
  const start = Date.parse(event.debugStartsAt || event.startsAt || 0);
  const end = Date.parse(event.debugEndsAt || event.endsAt || 0);
  if (Number.isFinite(start) && now < start) return false;
  if (Number.isFinite(end) && now > end) return false;
  return true;
}
function eventStatusAt(event, now) {
  const start = Date.parse(event?.startsAt || 0);
  const end = Date.parse(event?.endsAt || 0);
  if (!Number.isFinite(start) || !Number.isFinite(end)) return event?.status || 'upcoming';
  if (now < start) return 'upcoming';
  if (now < end) return 'live';
  return 'history';
}

function stateForDisplay(state) {
  if (!state) return state;
  const now = debugTimeMs(state);
  return {
    ...state,
    events: (state.events || [])
      .filter(e => isDebugEventVisible(e, state))
      .map((event) => {
        const status = eventStatusAt(event, now);
        if (status === event?.status && !(event?.papers || []).some((paper) => paper?.status !== status)) return event;
        return { ...event, status, papers: (event?.papers || []).map((paper) => ({ ...paper, status })) };
      }),
  };
}

function esc(s) { return String(s ?? '').replace(/[&<>"]/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch])); }
function fmtTime(iso) { return iso ? new Intl.DateTimeFormat('en', { weekday: 'short', hour: '2-digit', minute: '2-digit', timeZone: displayTimeZone() }).format(new Date(iso)) : '—'; }
function relativeTime(iso) {
  if (!iso) return '—';
  const now = latestState ? debugTimeMs(latestState) : Date.now();
  const diff = Math.round((now - new Date(iso).getTime()) / 1000);
  if (Math.abs(diff) < 10) return 'just now';
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  return fmtTime(iso);
}
function detailUrlFromPaper(p) {
  if (p?.detailUrl) return p.detailUrl;
  const info = p?.links?.info || '';
  if (info) return info;
  // MiniConf pages are keyed by the papers.csv uid, not by our paper/oral display ids.
  const uid = String(p?.sourcePaperId || '').trim() || (String(p?.id || '').match(/(?:^|-)paper-(\d+)$/) || [])[1] || '';
  return uid ? `${window.ISMIRSite.programSite}/poster_${encodeURIComponent(uid)}.html` : '';
}
function eventInfoUrl(e) {
  const links = e?.links || {};
  return e?.detailUrl || links.info || links.detail || '';
}
function eventTitleHtml(e) {
  const url = eventInfoUrl(e);
  const title = esc(e?.title || 'Untitled event');
  return url
    ? `<h3 class="card-title upcoming-card-title history-card-title"><a href="${esc(url)}" target="_blank" rel="noopener">${title}</a></h3>`
    : `<h3 class="card-title upcoming-card-title history-card-title">${title}</h3>`;
}
function actionLinks(links) {
  const safe = links || {};
  const items = [
    ['slack', 'Slack'],
    ['youtube', 'Livestream'],
    ['pdf', 'PDF'],
    ['video', 'Video'],
    ['poster', 'Poster'],
    ['slides', 'Slides'],
  ].filter(([key]) => safe[key]);
  if (!items.length) return '';
  return `<div class="link-row history-event-actions">${items.map(([key, label]) => `<a class="link-button" href="${esc(safe[key])}" target="_blank" rel="noopener">${label}</a>`).join('')}</div>`;
}
function fmtEndedTime(iso) {
  if (!iso) return '—';
  const parts = new Intl.DateTimeFormat('en-US', {
    month: 'short',
    day: 'numeric',
    weekday: 'short',
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
    timeZone: displayTimeZone(),
  }).formatToParts(new Date(iso));
  const get = (type) => parts.find((p) => p.type === type)?.value || '';
  return `${get('month')} ${get('day')} · ${get('weekday')} ${get('hour')}:${get('minute')} ${get('dayPeriod')}`.trim();
}
function peakBadge(metrics) {
  return `<span class="zoom-peak-badge history-peak-badge">Peak Zoom <strong>${metrics?.available === false ? '—' : Number(metrics?.peakZoom || 0)}</strong> online</span>`;
}
function historyPaperPanelId(e) {
  return `history-papers-${String(e?.id || 'session').replace(/[^a-zA-Z0-9_-]+/g, '-')}`;
}
function renderHistoryPaperToggle(e) {
  const papers = Array.isArray(e?.papers) ? e.papers : [];
  if (!papers.length) return '<span class="upcoming-paper-count-empty">0 papers</span>';
  const panelId = historyPaperPanelId(e);
  const expanded = expandedHistoryPaperEventIds.has(e.id);
  return `<button class="upcoming-paper-toggle history-paper-toggle" type="button" aria-expanded="${expanded ? 'true' : 'false'}" aria-controls="${esc(panelId)}" data-history-paper-toggle data-history-paper-event="${esc(e.id)}" data-paper-count="${papers.length}">
    ${papers.length} paper${papers.length === 1 ? '' : 's'} · ${expanded ? 'Collapse' : 'Expand'}
  </button>`;
}
function renderHistoryPaperPanel(e) {
  const papers = Array.isArray(e?.papers) ? e.papers : [];
  if (!papers.length) return '';
  const panelId = historyPaperPanelId(e);
  const expanded = expandedHistoryPaperEventIds.has(e.id);
  return `<div class="upcoming-paper-panel history-paper-panel" id="${esc(panelId)}"${expanded ? '' : ' hidden'}>
    <ol>
      ${papers.map((paper) => {
        const detailUrl = detailUrlFromPaper(paper);
        const content = `<span class="upcoming-paper-id">${esc(paper.displayId || paper.id)}</span><span class="upcoming-paper-title">${esc(paper.title)}</span>`;
        return `<li>${detailUrl ? `<a href="${esc(detailUrl)}" target="_blank" rel="noopener">${content}</a>` : `<span class="upcoming-paper-static">${content}</span>`}</li>`;
      }).join('')}
    </ol>
  </div>`;
}
function setConnection(online, label) {
  if (!connection) return;
  connection.textContent = label || (online ? 'Realtime connected' : 'Offline');
  connection.className = `connection ${online ? 'online' : 'offline'}`;
}
function groupTutorialEvents(events) {
  const groups = new Map(), result = [];
  for (const event of events) {
    if (event.type !== 'tutorial') { result.push(event); continue; }
    const key = JSON.stringify([event.startsAt, event.endsAt]);
    let group = groups.get(key);
    if (!group) {
      group = { ...event, id: `tutorials-${event.id}`, type: 'tutorial-group', title: 'Tutorials', links: {}, papers: [], tutorials: [] };
      groups.set(key, group); result.push(group);
    }
    group.tutorials.push(event);
  }
  return result;
}

function renderHistoryTutorials(group) {
  return `<article class="timeline-item upcoming-completed-card history-completed-card tutorial-group-card" data-event-type="tutorial-group">
    <div class="timeline-time upcoming-card-time history-ended-time">${group.endTimeTBD ? 'End time TBD' : 'Ended ' + esc(fmtEndedTime(group.endsAt))}</div>
    <h3 class="card-title upcoming-card-title">Tutorials</h3>
    <div class="tutorial-rows">${group.tutorials.map(e => `<div class="tutorial-row" data-event-id="${esc(e.id)}" data-event-type="tutorial">
      ${eventTitleHtml(e)}<div class="tutorial-row-actions">${Number(e.metrics?.peakZoom || 0) > 0 ? peakBadge(e.metrics) : ''}${actionLinks(e.links)}</div>
    </div>`).join('')}</div>
  </article>`;
}

function render(rawState) {
  if (!rawState) return;
  const incomingRevision = clockRevision(rawState);
  if (latestClockRevisionSeen >= 0 && incomingRevision < latestClockRevisionSeen) return;
  latestClockRevisionSeen = Math.max(latestClockRevisionSeen, incomingRevision);
  const state = stateForDisplay(rawState);
  latestState = state;
  conferenceTimeZone = state.conference?.timeZone || conferenceTimeZone;
  window.ISMIRTimeZone?.setReferenceDate?.(debugTimeMs(state));
  lastClockAuthoritySignature = clockAuthoritySignature(state);
  if (lastUpdated) lastUpdated.textContent = `Last updated ${relativeTime(state.updatedAt)}`;
  const history = (state.events || []).filter(e => e.status === 'history').sort((a, b) => new Date(b.endsAt) - new Date(a.endsAt));
  root.innerHTML = history.length ? groupTutorialEvents(history).map(e => {
    if (e.tutorials) return renderHistoryTutorials(e);
    const isPoster = e.type === 'poster';
    const hasPapers = Array.isArray(e.papers) && e.papers.length > 0;
    const peak = Number(e.metrics?.peakZoom || 0);
    const hadZoom = Boolean(e?.links?.zoom);
    const isPaperExpanded = hasPapers && expandedHistoryPaperEventIds.has(e.id);
    return `<article class="timeline-item upcoming-completed-card history-completed-card${isPoster ? ' upcoming-poster-card history-poster-card' : ''}${isPaperExpanded ? ' is-paper-expanded' : ''}" data-event-id="${esc(e.id)}" data-event-type="${esc(e.type || 'event')}">
      <div class="timeline-status-row history-card-status-row">
        <div class="timeline-time upcoming-card-time history-ended-time">${e.endTimeTBD ? 'End time TBD' : 'Ended ' + esc(fmtEndedTime(e.endsAt))}</div>
        ${(hadZoom || peak > 0) ? peakBadge(e.metrics) : ''}
      </div>
      <div class="history-title-actions-row">
        ${eventTitleHtml(e)}
        ${hasPapers ? renderHistoryPaperToggle(e) : ''}
        ${actionLinks(e.links)}
        ${hasPapers ? renderHistoryPaperPanel(e) : ''}
      </div>
    </article>`;
  }).join('') : '<article class="empty-card">No completed events yet.</article>';
}

function compactHistoryEventForPrompt(e) {
  const base = {
    id: e.id,
    type: e.type,
    title: e.title,
    topic: e.topic,
    venue: e.venue,
    startsAt: e.startsAt,
    endsAt: e.endsAt,
    peakZoomOnline: e.metrics?.available === false ? null : Number(e.metrics?.peakZoom || 0),
    summary: e.summary || '',
    links: e.links || {},
  };
  if (Array.isArray(e.papers) && e.papers.length) {
    base.paperCount = e.papers.length;
    base.papers = e.papers.map((p) => ({
      id: p.id,
      title: p.title,
      authors: p.authors,
      presenterMode: p.presenterMode,
      peakZoomOnline: p.metrics?.available === false ? null : Number(p.metrics?.peakZoom || 0),
      detailUrl: p.detailUrl || p.links?.info || '',
    }));
  }
  return base;
}

async function buildHistoryPrompt(state) {
  const display = stateForDisplay(state || latestState || { events: [] });
  const history = (display.events || [])
    .filter((e) => e.status === 'history')
    .sort((a, b) => new Date(b.endsAt) - new Date(a.endsAt))
    .slice(0, 40)
    .map(compactHistoryEventForPrompt);
  const snapshot = {
    conference: display.conference || {},
    generatedAt: new Date().toISOString(),
    serverNow: display.serverNow || display.updatedAt || null,
    completedEventCount: history.length,
    completedEvents: history,
  };
  return window.ISMIRPrompts.build('history', snapshot);
}

async function copyHistoryPrompt() {
  let prompt;
  if (copyHistoryPromptButton) copyHistoryPromptButton.disabled = true;
  if (historyCopyStatus) historyCopyStatus.textContent = 'Loading prompt…';
  try { prompt = await buildHistoryPrompt(latestState); }
  catch (err) {
    if (historyCopyStatus) historyCopyStatus.textContent = 'Could not load llm-prompts.json. Check the file and try again.';
    return;
  } finally { if (copyHistoryPromptButton) copyHistoryPromptButton.disabled = false; }
  try {
    await navigator.clipboard.writeText(prompt);
    if (historyCopyStatus) historyCopyStatus.textContent = 'Copied';
  } catch (err) {
    const ta = document.createElement('textarea');
    ta.value = prompt;
    ta.setAttribute('readonly', '');
    ta.style.position = 'fixed';
    ta.style.left = '-9999px';
    document.body.appendChild(ta);
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    if (historyCopyStatus) historyCopyStatus.textContent = 'Copied';
  }
  window.setTimeout(() => { if (historyCopyStatus) historyCopyStatus.textContent = ''; }, 1800);
}

async function fetchStateAtClockRevision(minRevision) {
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const stateRes = await fetch(`/api/state?_clock=${encodeURIComponent(String(minRevision))}&_=${Date.now()}`, { cache: 'no-store', credentials: 'same-origin' });
    const stateData = await stateRes.json();
    if (stateRes.ok && stateData?.ok && stateData.state && clockRevision(stateData.state) >= minRevision) return stateData.state;
    if (attempt === 0) await new Promise((resolve) => setTimeout(resolve, 180));
  }
  return null;
}

async function refreshClockAuthorityFallback() {
  if (publicStatic || clockAuthorityPollBusy || !latestState) return;
  clockAuthorityPollBusy = true;
  try {
    const clockRes = await fetch(`/api/debug-clock?_=${Date.now()}`, { cache: 'no-store', credentials: 'same-origin' });
    const clockData = await clockRes.json();
    if (!clockRes.ok || !clockData?.ok || !clockData.debugClock) return;
    const clockEnvelope = { debugClock: clockData.debugClock };
    const incomingRevision = clockRevision(clockEnvelope);
    if (incomingRevision < latestClockRevisionSeen) return;
    const incomingSignature = clockAuthoritySignature(clockEnvelope);
    if (incomingSignature === lastClockAuthoritySignature) return;

    latestClockRevisionSeen = Math.max(latestClockRevisionSeen, incomingRevision);
    const authoritativeState = await fetchStateAtClockRevision(incomingRevision);
    if (authoritativeState) {
      render(authoritativeState);
      return;
    }

    const mergedState = {
      ...latestState,
      debugClock: clockData.debugClock,
      serverNow: clockData.debugClock.serverNow || latestState.serverNow,
    };
    render(mergedState);
    lastClockAuthoritySignature = '';
  } catch (_) {
    // WebSocket is primary; this is only a missed-clock-update fallback.
  } finally {
    clockAuthorityPollBusy = false;
  }
}

async function fetchInitial() {
  if (publicStatic) {
    window.ISMIRPublic.start({ ...window.ISMIR_PUBLIC_CONFIG, onStatus: setConnection,
      onState: state => { latestClockRevisionSeen = -1; render(window.ISMIRSite?.localizeState(state) || state); } });
    return;
  }
  const res = await fetch('/api/state', { cache: 'no-store' });
  const data = await res.json();
  if (data.ok) render(data.state);
}
function connectWS() {
  if (publicStatic) return;
  clearTimeout(reconnectTimer);
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}/ws/public`);
  ws.onopen = () => setConnection(true, 'Realtime connected');
  ws.onmessage = (event) => { const msg = JSON.parse(event.data); if (msg.type === 'state') render(msg.state); };
  ws.onclose = () => { setConnection(false, 'Reconnecting…'); reconnectTimer = setTimeout(connectWS, 1500); };
  ws.onerror = () => setConnection(false, 'Connection issue');
}
window.addEventListener('ismir-timezone-change', () => { if (latestState) render(latestState); });
fetchInitial().catch(() => setConnection(false, 'Initial load failed'));
connectWS();
setInterval(refreshClockAuthorityFallback, 2000);
window.addEventListener('focus', refreshClockAuthorityFallback);
document.addEventListener('visibilitychange', () => {
  if (!document.hidden) refreshClockAuthorityFallback();
});
if (root) {
  root.addEventListener('click', (event) => {
    const button = event.target.closest('[data-history-paper-toggle]');
    if (!button) return;
    const panelId = button.getAttribute('aria-controls');
    const panel = panelId ? document.getElementById(panelId) : null;
    if (!panel) return;
    const opening = panel.hidden;
    panel.hidden = !opening;
    button.setAttribute('aria-expanded', opening ? 'true' : 'false');
    const paperCount = Number(button.dataset.paperCount || 0);
    button.textContent = `${paperCount} paper${paperCount === 1 ? '' : 's'} · ${opening ? 'Collapse' : 'Expand'}`;
    const eventId = button.dataset.historyPaperEvent || button.closest('[data-event-id]')?.dataset.eventId || '';
    if (eventId) {
      if (opening) expandedHistoryPaperEventIds.add(eventId);
      else expandedHistoryPaperEventIds.delete(eventId);
    }
    const card = button.closest('.history-completed-card');
    if (card) card.classList.toggle('is-paper-expanded', opening);
  });
}
if (copyHistoryPromptButton) copyHistoryPromptButton.addEventListener('click', copyHistoryPrompt);
