'use strict';
// Shared with the backend-hosted page: debug-clock and non-publicStatic code paths only run there.
const publicStatic = window.ISMIR_PUBLIC_CONFIG?.staticHosting === true;

const ISMIR_BUILD_VERSION = '1.0.0-ui.6';
window.ISMIR_BUILD_VERSION = ISMIR_BUILD_VERSION;

const els = {
  connection: document.getElementById('connection-status'),
  lastUpdated: document.getElementById('last-updated'),
  dashboard: document.getElementById('dashboard-grid'),
  spotlight: document.getElementById('spotlight-root'),
  live: document.getElementById('live-events-root'),
  upcoming: document.getElementById('upcoming-events-root'),
  copyLlmPrompt: document.getElementById('copy-llm-prompt'),
  copyLlmStatus: document.getElementById('llm-copy-status'),
  debugClockPanel: document.getElementById('debug-clock-panel'),
  debugClockForm: document.getElementById('debug-clock-form'),
  debugClockDate: document.getElementById('debug-clock-date'),
  debugClockHour: document.getElementById('debug-clock-hour'),
  debugClockMinute: document.getElementById('debug-clock-minute'),
  debugClockAmPm: document.getElementById('debug-clock-ampm'),
  debugClockNow: document.getElementById('debug-clock-now'),
  debugClockHint: document.getElementById('debug-clock-hint'),
  debugClockReset: document.getElementById('debug-clock-reset'),
};

let currentState = null;
let reconnectTimer = null;
let selectedPosterEventId = null;
const expandedLivePaperEventIds = new Set();
let lastTopologyKey = '';
let realtimeUpdateQueued = false;
let pendingRealtimeState = null;
let conferenceTimeZone = window.ISMIRSite.timeZone;
let debugClockPollTimer = null;
let latestDebugClockRevision = -1;
let lastClockAuthoritySignature = '';
let clockAuthorityPollBusy = false;
let latestClockRevisionSeen = -1;

function displayTimeZone() {
  return window.ISMIRTimeZone?.getTimeZone?.() || (() => {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || conferenceTimeZone; }
    catch (_) { return conferenceTimeZone; }
  })();
}

const pageParams = new URLSearchParams(location.search);
const debugMode = !publicStatic && ['1', 'true', 'yes'].includes(String(pageParams.get('debug') || '').toLowerCase());
const initialDebugNowParam = pageParams.get('debugNow') || pageParams.get('fakeNow') || pageParams.get('now') || '';
function captureDebugClockKey() {
  if (!debugMode) return '';
  const hashParams = new URLSearchParams(String(location.hash || '').replace(/^#/, ''));
  const secret = String(hashParams.get('key') || hashParams.get('debugKey') || '').trim();
  if (secret) {
    // Use the fragment only for this page load, then remove it from the visible URL/history.
    const cleaned = new URL(location.href);
    cleaned.hash = '';
    history.replaceState(null, '', `${cleaned.pathname}${cleaned.search}`);
  }
  return secret;
}
const debugClockKey = captureDebugClockKey();
function debugClockAuthHeaders(extra = {}) {
  return debugClockKey ? { ...extra, 'X-Debug-Key': debugClockKey } : extra;
}
function setDebugClockControlsEnabled(enabled) {
  [els.debugClockDate, els.debugClockHour, els.debugClockMinute, els.debugClockAmPm, els.debugClockReset]
    .filter(Boolean)
    .forEach((control) => { control.disabled = !enabled; });
  const submit = els.debugClockForm?.querySelector('button[type="submit"]');
  if (submit) submit.disabled = !enabled;
}
if (debugMode) document.documentElement.classList.add('debug-clock-only');

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

function applyDebugWindowStatus(event, state) {
  if (!event?.debugOnly || !debugMode) return event;
  const now = debugTimeMs(state);
  const start = Date.parse(event.debugStartsAt || event.startsAt || 0);
  const end = Date.parse(event.debugEndsAt || event.endsAt || 0);
  let status = event.status;
  if (Number.isFinite(start) && now < start) status = 'upcoming';
  else if (Number.isFinite(end) && now > end) status = 'history';
  else status = 'live';
  return {
    ...event,
    status,
    papers: (event.papers || []).map((paper) => ({ ...paper, status })),
  };
}

function eventStatusAt(event, now) {
  const start = Date.parse(event?.startsAt || 0);
  const end = Date.parse(event?.endsAt || 0);
  if (!Number.isFinite(start) || !Number.isFinite(end)) return event?.status || 'upcoming';
  if (now < start) return 'upcoming';
  if (now < end) return 'live';
  return 'history';
}

function applyAuthoritativeClockStatus(event, state) {
  if (event?.debugOnly && debugMode) return applyDebugWindowStatus(event, state);
  const status = eventStatusAt(event, debugTimeMs(state));
  if (status === event?.status && !(event?.papers || []).some((paper) => paper?.status !== status)) return event;
  return {
    ...event,
    status,
    papers: (event?.papers || []).map((paper) => ({ ...paper, status })),
  };
}

function stateForDisplay(state) {
  if (!state) return state;
  return {
    ...state,
    events: (state.events || [])
      .filter(e => isDebugEventVisible(e, state))
      .map(e => applyAuthoritativeClockStatus(e, state)),
  };
}

function fmtTime(iso) {
  if (!iso) return '—';
  return new Intl.DateTimeFormat('en-US', { hour: '2-digit', minute: '2-digit', hour12: true, timeZone: displayTimeZone() }).format(new Date(iso));
}

function fmtUtcOffset(iso) {
  const date = iso ? new Date(iso) : new Date();
  return window.ISMIRTimeZone?.getUTCOffset?.(date) || 'UTC';
}

function fmtDateTime(iso) {
  if (!iso) return '—';
  return new Intl.DateTimeFormat('en', { weekday: 'short', hour: '2-digit', minute: '2-digit', timeZone: displayTimeZone() }).format(new Date(iso));
}

function fmtNextEventDateTime(iso) {
  if (!iso) return '—';
  const date = new Date(iso);
  const day = new Intl.DateTimeFormat('en-US', { weekday: 'short', timeZone: displayTimeZone() }).format(date);
  const time = new Intl.DateTimeFormat('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
    timeZone: displayTimeZone(),
  }).format(date);
  return `${day} ${time} · ${fmtUtcOffset(iso)}`;
}

function timeUntilEvent(iso, state) {
  if (!iso) return 'No upcoming event';
  const target = Date.parse(iso);
  const now = state ? debugTimeMs(state) : Date.now();
  if (!Number.isFinite(target) || !Number.isFinite(now)) return '—';
  const diffMs = target - now;
  if (diffMs <= 0) return 'starting now';
  const mins = Math.ceil(diffMs / 60000);
  if (mins <= 1) return 'in 1 min';
  if (mins < 60) return `in ${mins} min`;
  const hours = diffMs / 3600000;
  if (hours < 24) {
    const rounded = Math.max(1, Math.round(hours));
    return `in ${rounded} hr`;
  }
  if (hours < 48) return 'tomorrow';
  const days = Math.max(2, Math.round(hours / 24));
  return `in ${days} days`;
}

function fmtFullDate(iso) {
  if (!iso) return '—';
  return new Intl.DateTimeFormat('en', { weekday: 'short', month: 'short', day: '2-digit', year: 'numeric', timeZone: displayTimeZone() }).format(new Date(iso));
}

function fmtShortDate(iso) {
  if (!iso) return '—';
  return new Intl.DateTimeFormat('en', { month: 'short', day: '2-digit', timeZone: displayTimeZone() }).format(new Date(iso));
}

function fmtDayName(iso) {
  if (!iso) return '—';
  return new Intl.DateTimeFormat('en', { weekday: 'short', timeZone: displayTimeZone() }).format(new Date(iso));
}

function fmtMonthDay(iso) {
  if (!iso) return '—';
  return new Intl.DateTimeFormat('en', { month: 'short', day: '2-digit', timeZone: displayTimeZone() }).format(new Date(iso));
}

function fmtYear(iso) {
  if (!iso) return '—';
  return new Intl.DateTimeFormat('en', { year: 'numeric', timeZone: displayTimeZone() }).format(new Date(iso));
}

function timelineDateKey(iso) {
  if (!iso) return '';
  const parts = new Intl.DateTimeFormat('en', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    timeZone: displayTimeZone(),
  }).formatToParts(new Date(iso));
  const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

function fmtTimelineDate(iso) {
  if (!iso) return '—';
  const parts = new Intl.DateTimeFormat('en', {
    month: 'short',
    day: '2-digit',
    weekday: 'short',
    timeZone: displayTimeZone(),
  }).formatToParts(new Date(iso));
  const values = Object.fromEntries(parts.map(part => [part.type, part.value]));
  return `${values.month} ${values.day} · ${values.weekday}`;
}

function fmtTimelineTime(iso) {
  if (!iso) return '—';
  return new Intl.DateTimeFormat('en-US', {
    hour: '2-digit',
    minute: '2-digit',
    hour12: true,
    timeZone: displayTimeZone(),
  }).format(new Date(iso));
}

function relativeTime(iso) {
  if (!iso) return '—';
  const now = currentState ? debugTimeMs(currentState) : Date.now();
  const diff = Math.round((now - new Date(iso).getTime()) / 1000);
  if (Math.abs(diff) < 10) return 'just now';
  if (diff < 60) return `${diff}s ago`;
  if (diff < 3600) return `${Math.round(diff / 60)}m ago`;
  return fmtTime(iso);
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"]/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]));
}

function findByAttr(root, name, value) {
  if (!root) return null;
  const nodes = root.querySelectorAll(`[${name}]`);
  return Array.from(nodes).find((el) => el.getAttribute(name) === String(value)) || null;
}

function topologyKey(state) {
  return JSON.stringify((state.events || []).map((e) => ({
    id: e.id,
    type: e.type,
    status: e.status,
    spotlight: Boolean(e.spotlight),
    papers: (e.papers || []).map((p) => p.id),
  })));
}

function byStart(a, b) { return new Date(a.startsAt) - new Date(b.startsAt); }
function byEndDesc(a, b) { return new Date(b.endsAt) - new Date(a.endsAt); }
function getLiveEvents(state) { return (state.events || []).filter(e => e.status === 'live').sort(byStart); }
function getUpcomingEvents(state) { return (state.events || []).filter(e => e.status === 'upcoming').sort(byStart); }
function getPosterEvents(state) { return getLiveEvents(state).filter(e => e.type === 'poster' && !e.spotlight); }
function getAllPosterPapers(state) { return getPosterEvents(state).flatMap(e => e.papers || []); }

function speakerInfo(paper) {
  if (paper?.status === 'history') return { talking: false, name: 'Ended', transcript: '', label: 'Ended' };
  if (paper?.status === 'upcoming') return { talking: false, name: 'Not started', transcript: '', label: 'Not started' };
  const live = paper?.live || {};
  if (live.observerConnected !== true) {
    return { talking: false, disconnected: true, name: 'Not connected', transcript: '', label: 'Not connected' };
  }
  // Public cards use three simple states; telemetry details stay in the Observer app.
  if (live.speakerState === 'unknown') return { talking: false, name: '', transcript: '', label: 'No one is speaking' };
  const talking = Boolean(live.activeSpeakerTalking || live.presenterTalking || live.audienceTalking);
  const candidates = [live.activeSpeakerName, live.speakerName, live.activeSpeakerLabel];
  for (const role of ['presenter', 'audience']) {
    const text = String(live[`${role}Transcript`] || '').trim();
    const match = text.match(/^Active speaker:\s*(.+)$/i);
    if (match) candidates.push(match[1]);
    else if (live[`${role}Talking`]) candidates.push(text);
  }
  const name = candidates.map(x => String(x || '').trim()).find(Boolean) || 'Someone';
  const transcript = live.activeSpeakerTranscript || live.presenterTranscript || live.audienceTranscript || '';
  return { talking, name, transcript, label: talking ? `${name} is speaking` : 'No one is speaking' };
}

function isCurrentConversationActive(paper) {
  // Active conversations are intentionally realtime, not peak attendance.
  // A poster Zoom room with silent attendees should count as 0 active conversations;
  // it becomes active only while a speaker signal is currently held/fresh.
  return paper?.status === 'live' && speakerInfo(paper).talking;
}

function countActiveConversations(event) {
  return (event.papers || []).filter(isCurrentConversationActive).length;
}

function detailUrlFromPaper(p) {
  if (p?.detailUrl) return p.detailUrl;
  // MiniConf pages are keyed by the papers.csv uid, not by our paper/oral display ids.
  const uid = String(p?.sourcePaperId || '').trim() || (String(p?.id || '').match(/(?:^|-)paper-(\d+)$/) || [])[1] || '';
  return uid ? `${window.ISMIRSite.programSite}/poster_${encodeURIComponent(uid)}.html` : '';
}

function eventInfoUrl(e) {
  const links = e?.links || {};
  return e?.detailUrl || links.info || links.detail || '';
}

function eventTitleHtml(e, className = 'card-title') {
  const url = eventInfoUrl(e);
  const title = esc(e.title);
  return url
    ? `<h3 class="${className}"><a href="${esc(url)}" target="_blank" rel="noopener">${title}</a></h3>`
    : `<h3 class="${className}">${title}</h3>`;
}

function upcomingEventTitleHtml(e) {
  const url = eventInfoUrl(e);
  const rawTitle = String(e?.title || '');
  let titleHtml = esc(rawTitle);
  if (e?.type === 'keynote') {
    const match = rawTitle.match(/^((?:Keynote\s*-\s*\d+)\s*:)(?:\s*)(.+)$/i);
    if (match) {
      titleHtml = `<span class="upcoming-title-prefix">${esc(match[1])}</span> <span class="upcoming-title-detail">${esc(match[2])}</span>`;
    }
  }
  return url
    ? `<h3 class="card-title upcoming-title" title="${esc(rawTitle)}"><a href="${esc(url)}" target="_blank" rel="noopener">${titleHtml}</a></h3>`
    : `<h3 class="card-title upcoming-title" title="${esc(rawTitle)}">${titleHtml}</h3>`;
}

function linkRow(links, opts = {}) {
  const safe = links || {};
  const showInfo = opts.showInfo !== false;
  const infoUrl = opts.infoUrl || safe.info || safe.detail || '';
  const zoomId = String(opts.zoomId || '');
  return `<div class="link-row">
    ${showInfo && infoUrl ? `<a class="link-button info-link" href="${esc(infoUrl)}" target="_blank" rel="noopener">Info</a>` : ''}
    ${safe.slack ? `<a class="link-button" href="${esc(safe.slack)}" target="_blank" rel="noopener">Slack</a>` : ''}
    ${safe.zoom ? `<a class="link-button"${zoomId ? ` id="${esc(zoomId)}"` : ''} href="${esc(safe.zoom)}" target="_blank" rel="noopener">Zoom</a>` : ''}
    ${safe.youtube ? `<a class="link-button" href="${esc(safe.youtube)}" target="_blank" rel="noopener">Livestream</a>` : ''}
    ${safe.pdf ? `<a class="link-button" href="${esc(safe.pdf)}" target="_blank" rel="noopener">PDF</a>` : ''}
    ${safe.video ? `<a class="link-button" href="${esc(safe.video)}" target="_blank" rel="noopener">Video</a>` : ''}
    ${safe.poster ? `<a class="link-button" href="${esc(safe.poster)}" target="_blank" rel="noopener">Poster</a>` : ''}
    ${safe.slides ? `<a class="link-button" href="${esc(safe.slides)}" target="_blank" rel="noopener">Slides</a>` : ''}
  </div>`;
}

function zoomCountPresentation(h = {}) {
  if (h?.available === false && !h?.partial) return { count: '?', prefix: '', title: 'Zoom participant count unavailable' };
  const count = String(Number(h?.zoom || 0));
  if (h?.partial) return { count, prefix: '≥', title: 'Partial Zoom count from currently reporting poster lobby and breakout rooms' };
  return { count, prefix: '', title: '' };
}

function liveZoomBadge(h, key = '') {
  const shown = zoomCountPresentation(h);
  return `<span class="zoom-live-badge" ${key ? `data-zoom-badge="${esc(key)}"` : ''}${shown.title ? ` title="${esc(shown.title)}"` : ''}><span class="pulse-dot"></span><span data-zoom-prefix>${shown.prefix}</span><strong data-zoom-count>${shown.count}</strong> online on Zoom</span>`;
}

function peakZoomBadge(metrics, key = '') {
  return `<span class="zoom-peak-badge" ${key ? `data-peak-badge="${esc(key)}"` : ''}>Peak <strong data-peak-count>${metrics?.available === false ? '?' : Number(metrics?.peakZoom || 0)}</strong> online</span>`;
}

function upcomingBadge(e) {
  return `<span class="upcoming-badge">Starts ${fmtShortDate(e.startsAt)} · ${fmtTime(e.startsAt)} · ${esc(fmtUtcOffset(e.startsAt))}</span>`;
}

function eventBadge(e, key = '') {
  if (e.status === 'live') return e?.links?.zoom ? liveZoomBadge(e.headcounts, key) : '';
  if (e.status === 'history') return peakZoomBadge(e.metrics, key);
  return upcomingBadge(e);
}

function paperBadge(p) {
  if (p.status === 'live') return liveZoomBadge(p.headcounts, `paper:${p.id}`);
  if (p.status === 'history') return peakZoomBadge(p.metrics, `paper:${p.id}`);
  return `<span class="upcoming-badge">Scheduled</span>`;
}

function eventMeta(e) {
  return `${fmtTime(e.startsAt)}–${(e.endTimeTBD ? 'TBD' : fmtTime(e.endsAt))} · ${esc(e.venue || 'Venue TBA')} · ${esc(e.topic || '')}`;
}

function presenterLabel(mode) {
  if (!mode) return 'Presentation mode TBA';
  const clean = String(mode).toLowerCase();
  if (clean === 'online') return 'Presented Virtual';
  if (clean === 'mixed') return 'Presented In-person + Virtual';
  return 'Presented In-person';
}

function statCard(key, label, value, help) {
  return `<article class="stat-card" data-stat-card="${esc(key)}">
    <div class="stat-label">${esc(label)}</div>
    <div class="stat-value" data-stat-value>${esc(value)}</div>
    <div class="stat-help" data-stat-help>${esc(help)}</div>
  </article>`;
}

function dashboardStats(state) {
  const events = state.events || [];
  const liveEvents = events.filter(e => e.status === 'live');
  const upcomingEvents = getUpcomingEvents(state);
  const posterEvents = liveEvents.filter(e => e.type === 'poster');
  const papers = posterEvents.flatMap(e => e.papers || []);
  const activeConversations = posterEvents.reduce((sum, e) => sum + countActiveConversations(e), 0);
  const zoomEvents = liveEvents.filter(e => e?.links?.zoom);
  const fresh = zoomEvents.filter(e => e.headcounts?.available !== false);
  const sum = fresh.reduce((n, e) => n + Number(e.headcounts?.zoom || 0), 0);
  // Offline states drop Zoom links and live signals, so their counts would read as a misleading 0.
  const zoom = state.offline ? '?' : fresh.length === zoomEvents.length ? sum : fresh.length ? `≥${sum}` : '?';
  const next = upcomingEvents[0];
  return {
    liveEvents: ['Live events', liveEvents.length, 'events currently active'],
    zoomAttendees: ['Zoom attendees', zoom, 'summed live Zoom headcounts'],
    activeConversations: ['Recent conversations', state.offline ? '?' : activeConversations, `${state.offline ? '?' : activeConversations}/${papers.length} poster rooms with recent speaker signals`],
    nextEvent: ['Next event', next ? fmtNextEventDateTime(next.startsAt) : '—', next ? timeUntilEvent(next.startsAt, state) : 'No upcoming scheduled event'],
  };
}


function compactEventForPrompt(e) {
  const base = {
    id: e.id,
    type: e.type,
    status: e.status,
    title: e.title,
    time: `${fmtDateTime(e.startsAt)}-${(e.endTimeTBD ? 'TBD' : fmtTime(e.endsAt))}`,
    venue: e.venue || 'Venue TBA',
    topic: e.topic || '',
    zoomOnline: e.headcounts?.available === false ? null : Number(e.headcounts?.zoom || 0),
    peakZoomOnline: e.metrics?.available === false ? null : Number(e.metrics?.peakZoom || 0),
  };
  if (e.type === 'poster') base.mainRoomOnline = e.headcounts?.available === false ? null : Number(e.headcounts?.lobbyZoom || 0);
  if (sessionHasPapers(e)) {
    if (e.type === 'poster') base.activeConversations = countActiveConversations(e);
    base.papers = (e.papers || []).map((p) => ({
      id: p.id,
      title: p.title,
      authors: p.authors,
      status: p.status,
      zoomOnline: p.headcounts?.available === false ? null : Number(p.headcounts?.zoom || 0),
      peakZoomOnline: p.metrics?.available === false ? null : Number(p.metrics?.peakZoom || 0),
      speaker: speakerInfo(p).label,
      presenterMode: presenterLabel(p.presenterMode),
      detailUrl: detailUrlFromPaper(p),
    }));
  }
  return base;
}

async function buildLlmAttendancePrompt(state) {
  const display = stateForDisplay(state || currentState || { events: [] });
  const live = getLiveEvents(display).map(compactEventForPrompt);
  const upcoming = getUpcomingEvents(display).slice(0, 12).map(compactEventForPrompt);
  const dashboard = dashboardStats(display);
  const snapshot = {
    conference: display.conference || {},
    generatedAt: new Date().toISOString(),
    serverNow: display.serverNow || display.updatedAt || null,
    dashboard: Object.fromEntries(Object.entries(dashboard).map(([k, v]) => [k, { label: v[0], value: v[1], note: v[2] }])),
    liveEvents: live,
    upcomingEvents: upcoming,
  };
  return window.ISMIRPrompts.build('overview', snapshot);
}

function pad2(value) { return String(value).padStart(2, '0'); }
function tzParts(date, timeZone) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone,
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
    hourCycle: 'h23',
  }).formatToParts(date);
  const out = {};
  for (const part of parts) if (part.type !== 'literal') out[part.type] = part.value;
  return out;
}
function timeZoneOffsetMs(utcMs, timeZone) {
  const p = tzParts(new Date(utcMs), timeZone);
  const asUtc = Date.UTC(Number(p.year), Number(p.month) - 1, Number(p.day), Number(p.hour), Number(p.minute), Number(p.second));
  return asUtc - utcMs;
}
function zonedLocalInputToIso(value, timeZone) {
  const match = String(value || '').match(/^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/);
  if (!match) return '';
  const [, y, mo, d, h, mi] = match.map(Number);
  let guess = Date.UTC(y, mo - 1, d, h, mi, 0);
  let offset = timeZoneOffsetMs(guess, timeZone);
  let utc = guess - offset;
  const secondOffset = timeZoneOffsetMs(utc, timeZone);
  if (secondOffset !== offset) utc = guess - secondOffset;
  return new Date(utc).toISOString();
}
function zonedDateTimeFieldsFromIso(iso, timeZone) {
  const ms = Date.parse(iso || '');
  if (!Number.isFinite(ms)) return null;
  const p = tzParts(new Date(ms), timeZone);
  const hour24 = Number(p.hour);
  const ampm = hour24 >= 12 ? 'PM' : 'AM';
  const hour12 = hour24 % 12 || 12;
  return { date: `${p.year}-${p.month}-${p.day}`, hour: String(hour12), minute: p.minute, ampm };
}
function debugClockLocalValue() {
  const date = String(els.debugClockDate?.value || '');
  const hour12 = Number(els.debugClockHour?.value || 0);
  const minute = Number(els.debugClockMinute?.value || 0);
  const ampm = String(els.debugClockAmPm?.value || 'AM');
  if (!/^\d{4}-\d{2}-\d{2}$/.test(date) || hour12 < 1 || hour12 > 12 || minute < 0 || minute > 59) return '';
  let hour24 = hour12 % 12;
  if (ampm === 'PM') hour24 += 12;
  return `${date}T${String(hour24).padStart(2, '0')}:${String(minute).padStart(2, '0')}`;
}
function fillDebugClockSelects() {
  if (els.debugClockHour && !els.debugClockHour.options.length) {
    for (let hour = 1; hour <= 12; hour += 1) els.debugClockHour.add(new Option(String(hour), String(hour)));
  }
  if (els.debugClockMinute && !els.debugClockMinute.options.length) {
    for (let minute = 0; minute < 60; minute += 1) {
      const value = String(minute).padStart(2, '0');
      els.debugClockMinute.add(new Option(value, value));
    }
  }
}
function setDebugClockFieldsFromIso(iso, timeZone) {
  const fields = zonedDateTimeFieldsFromIso(iso, timeZone);
  if (!fields) return;
  fillDebugClockSelects();
  if (els.debugClockDate) els.debugClockDate.value = fields.date;
  if (els.debugClockHour) els.debugClockHour.value = fields.hour;
  if (els.debugClockMinute) els.debugClockMinute.value = fields.minute;
  if (els.debugClockAmPm) els.debugClockAmPm.value = fields.ampm;
}
function formatDebugClockNow(iso) {
  if (!iso) return 'Server time —';
  const label = new Intl.DateTimeFormat('en', {
    weekday: 'short', month: 'short', day: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: true,
    timeZone: displayTimeZone(),
  }).format(new Date(iso));
  return `Server time ${label}`;
}
function renderDebugClock(state) {
  if (!els.debugClockPanel) return;
  els.debugClockPanel.hidden = !debugMode;
  if (!debugMode) return;
  const clock = state?.debugClock || {};
  if (Number.isFinite(Number(clock.revision))) latestDebugClockRevision = Math.max(latestDebugClockRevision, Number(clock.revision));
  const nowMs = debugTimeMs(state);
  const nowIso = Number.isFinite(nowMs) ? new Date(nowMs).toISOString() : (clock.serverNow || state?.serverNow || '');
  if (els.debugClockNow) {
    const zone = displayTimeZone();
    const offset = window.ISMIRTimeZone?.getOffsetLabel?.() || '';
    els.debugClockNow.textContent = `${formatDebugClockNow(nowIso)} · ${zone}${offset ? ` · ${offset}` : ''}`;
  }
  const debugFields = [els.debugClockDate, els.debugClockHour, els.debugClockMinute, els.debugClockAmPm].filter(Boolean);
  if (!debugFields.includes(document.activeElement)) setDebugClockFieldsFromIso(nowIso, displayTimeZone());
  const hasKey = Boolean(debugClockKey);
  setDebugClockControlsEnabled(hasKey);
  if (els.debugClockHint) {
    els.debugClockHint.textContent = !hasKey
      ? 'Open this page with ?debug=1#key=YOUR_DEBUG_CLOCK_KEY to change the conference clock.'
      : clock.enabled
        ? 'Fixed conference time is active. All connected pages and Zoom observers use this same time.'
        : 'Real current time is active. All connected pages and Zoom observers follow the server clock.';
  }
}
async function refreshDebugClockPanel() {
  if (!debugMode) return;
  try {
    const res = await fetch('/api/debug-clock', { cache: 'no-store', credentials: 'same-origin' });
    const data = await res.json();
    if (!res.ok || !data.ok || !data.debugClock) throw new Error(data.error || 'Clock API unavailable');
    const incomingRevision = Number(data.debugClock.revision || 0);
    if (incomingRevision < latestDebugClockRevision) return;
    latestDebugClockRevision = incomingRevision;
    const nextState = { ...(currentState || {}), debugClock: data.debugClock, serverNow: data.debugClock.serverNow };
    currentState = nextState;
    renderDebugClock(nextState);
  } catch (error) {
    if (els.debugClockHint) els.debugClockHint.textContent = 'Conference clock server unavailable. The last confirmed clock state is shown.';
  }
}

async function setDebugClockFromForm(event) {
  event.preventDefault();
  const localValue = debugClockLocalValue();
  const fakeNow = zonedLocalInputToIso(localValue, displayTimeZone());
  if (!fakeNow) {
    if (els.debugClockHint) els.debugClockHint.textContent = 'Please choose a valid date, time, and AM/PM value.';
    return;
  }
  const res = await fetch('/api/debug-clock', {
    method: 'POST',
    credentials: 'same-origin',
    headers: debugClockAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ fakeNow, speed: 0 }),
  });
  const data = await res.json();
  if (!data.ok) {
    if (els.debugClockHint) els.debugClockHint.textContent = data.error || 'Failed to set debug clock.';
    return;
  }
  const nextState = data.state || { ...(currentState || {}), debugClock: data.debugClock, serverNow: data.debugClock?.serverNow };
  currentState = nextState;
  renderDebugClock(nextState);
  await refreshDebugClockPanel();
}
async function resetDebugClock() {
  const res = await fetch('/api/debug-clock', { method: 'DELETE', credentials: 'same-origin', headers: debugClockAuthHeaders() });
  const data = await res.json();
  if (!data.ok) {
    if (els.debugClockHint) els.debugClockHint.textContent = data.error || 'Failed to reset debug clock.';
    return;
  }
  const nextState = data.state || { ...(currentState || {}), debugClock: data.debugClock, serverNow: data.debugClock?.serverNow };
  currentState = nextState;
  renderDebugClock(nextState);
  await refreshDebugClockPanel();
}
async function applyInitialDebugNowParam() {
  if (!debugMode || !initialDebugNowParam) return false;
  const hasExplicitZone = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(String(initialDebugNowParam).trim());
  const directIso = hasExplicitZone && Number.isFinite(Date.parse(initialDebugNowParam)) ? new Date(Date.parse(initialDebugNowParam)).toISOString() : '';
  const fakeNow = directIso || zonedLocalInputToIso(initialDebugNowParam, displayTimeZone());
  if (!fakeNow) return false;
  const res = await fetch('/api/debug-clock', {
    method: 'POST',
    credentials: 'same-origin',
    headers: debugClockAuthHeaders({ 'Content-Type': 'application/json' }),
    body: JSON.stringify({ fakeNow, speed: 0 }),
  });
  return res.ok;
}

async function copyLlmPrompt() {
  let prompt;
  if (els.copyLlmPrompt) els.copyLlmPrompt.disabled = true;
  if (els.copyLlmStatus) els.copyLlmStatus.textContent = 'Loading prompt…';
  try { prompt = await buildLlmAttendancePrompt(currentState); }
  catch (err) {
    if (els.copyLlmStatus) els.copyLlmStatus.textContent = 'Could not load llm-prompts.json. Check the file and try again.';
    return;
  } finally { if (els.copyLlmPrompt) els.copyLlmPrompt.disabled = false; }
  try {
    await navigator.clipboard.writeText(prompt);
    if (els.copyLlmStatus) els.copyLlmStatus.textContent = 'Copied';
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
    if (els.copyLlmStatus) els.copyLlmStatus.textContent = 'Copied';
  }
  window.setTimeout(() => { if (els.copyLlmStatus) els.copyLlmStatus.textContent = ''; }, 1800);
}

const DASHBOARD_STAT_KEYS = ['liveEvents', 'zoomAttendees', 'activeConversations', 'nextEvent'];

function renderDashboard(state) {
  if (!els.dashboard) return;
  const stats = dashboardStats(state);
  els.dashboard.innerHTML = DASHBOARD_STAT_KEYS.map((key) => {
    const [label, value, help] = stats[key];
    return statCard(key, label, value, help);
  }).join('');
}

function updateDashboard(state) {
  if (!els.dashboard) return;
  const stats = dashboardStats(state);
  if (!els.dashboard.querySelector('[data-stat-card]')) {
    renderDashboard(state);
    return;
  }
  for (const key of DASHBOARD_STAT_KEYS) {
    const [, value, help] = stats[key];
    const card = findByAttr(els.dashboard, 'data-stat-card', key);
    if (!card) {
      renderDashboard(state);
      return;
    }
    const valueEl = card.querySelector('[data-stat-value]');
    const helpEl = card.querySelector('[data-stat-help]');
    if (valueEl && valueEl.textContent !== String(value)) valueEl.textContent = String(value);
    if (helpEl && helpEl.textContent !== String(help)) helpEl.textContent = String(help);
  }
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

function tutorialRows(group, live) {
  return `<div class="tutorial-rows">${group.tutorials.map(e => `<div class="tutorial-row" data-event-id="${esc(e.id)}" data-event-type="tutorial">
    ${eventTitleHtml(e, 'card-title tutorial-row-title')}
    <div class="tutorial-row-actions">${live ? eventBadge(e, `event:${e.id}`) : ''}${live ? linkRow(e.links, { showInfo: false }) : upcomingSlackLink(e)}</div>
  </div>`).join('')}</div>`;
}
function upcomingSlackLink(e) {
  return e?.links?.slack ? `<div class="link-row history-event-actions upcoming-event-actions"><a class="link-button" href="${esc(e.links.slack)}" target="_blank" rel="noopener">Slack</a></div>` : '';
}
function renderLiveTutorials(group) {
  return `<article class="event-card tutorial-group-card is-paper-expanded" data-event-type="tutorial-group">
    <div class="live-event-card-body"><div class="live-event-header"><div class="live-event-title-block">
      <h3 class="card-title live-card-title">Tutorials</h3>${liveOngoingMeta(group)}
    </div></div></div>
    <div class="live-session-paper-list-panel live-tutorial-list"><ol>${group.tutorials.map(e => {
      const match = String(e.title || '').match(/^(T\d+\s*\([^)]+\))\s*[:：–—-]?\s*(.*)$/i);
      const label = match ? match[1] : 'Tutorial';
      const title = match ? match[2] : e.title;
      const content = `<span class="upcoming-paper-id">${esc(label)}</span><span class="upcoming-paper-title">${esc(title)}</span>`;
      const url = eventInfoUrl(e);
      return `<li class="live-tutorial-row" data-event-id="${esc(e.id)}" data-event-type="tutorial">
        ${url ? `<a class="live-tutorial-title" href="${esc(url)}" target="_blank" rel="noopener">${content}</a>` : `<span class="live-tutorial-title">${content}</span>`}
        <div class="live-tutorial-actions">${eventBadge(e, `event:${e.id}`)}${linkRow(e.links, { showInfo: false })}</div>
      </li>`;
    }).join('')}</ol></div>
  </article>`;
}

function sessionHasPapers(e) {
  return Array.isArray(e?.papers) && e.papers.length > 0;
}

function paperToggleText(e, expanded) {
  const count = Array.isArray(e?.papers) ? e.papers.length : 0;
  return `${count} paper${count === 1 ? '' : 's'} · ${expanded ? 'Collapse' : 'Expand'}`;
}

function renderCompactLivePaperPanel(e) {
  const papers = e?.papers || [];
  if (!papers.length) return '';
  return `<div class="live-session-paper-list-panel" data-live-session-paper-panel="${esc(e.id)}">
    <ol>
      ${papers.map((paper) => {
        const detailUrl = detailUrlFromPaper(paper);
        const content = `<span class="upcoming-paper-id">${esc(paper.displayId || paper.id)}</span><span class="upcoming-paper-title">${esc(paper.title)}</span>`;
        return `<li>${detailUrl ? `<a href="${esc(detailUrl)}" target="_blank" rel="noopener">${content}</a>` : `<span>${content}</span>`}</li>`;
      }).join('')}
    </ol>
  </div>`;
}


function liveOngoingMeta(e) {
  return `<div class="live-ongoing-meta"><strong>Ongoing</strong><span aria-hidden="true"> · </span><time datetime="${esc(e.startsAt)}">${fmtTime(e.startsAt)}</time><span aria-hidden="true">–</span><time datetime="${esc(e.endsAt)}">${(e.endTimeTBD ? 'TBD' : fmtTime(e.endsAt))}</time><span class="live-event-timezone">· ${esc(fmtUtcOffset(e.startsAt))}</span></div>`;
}

function renderEventCard(e, opts = {}) {
  const zoomLinked = Boolean(e?.links?.zoom);
  const cardClass = opts.spotlight ? 'spotlight-card' : 'event-card';
  const badge = eventBadge(e, `event:${e.id}`);
  const hasPapers = sessionHasPapers(e);
  const papersExpanded = expandedLivePaperEventIds.has(e.id);
  return `<article class="${cardClass}${zoomLinked ? ' live-zoom-linked-card' : ''}${papersExpanded ? ' is-paper-expanded' : ''}" data-event-id="${esc(e.id)}" data-event-type="${esc(e.type || 'event')}">
    <div class="live-event-card-body">
      <div class="live-event-header">
        <div class="live-event-title-block">
          ${eventTitleHtml(e, 'card-title live-card-title')}
          ${liveOngoingMeta(e)}
        </div>
        ${badge ? `<div class="live-event-status-stack">${badge}</div>` : ''}
      </div>
      <div class="live-event-actions live-session-actions">
        ${linkRow(e.links, { showInfo: false })}
        ${hasPapers ? `<button class="link-button live-session-paper-toggle" type="button" data-live-session-paper-toggle="${esc(e.id)}" aria-expanded="${papersExpanded ? 'true' : 'false'}"><span aria-hidden="true">${papersExpanded ? '−' : '+'}</span> ${esc(paperToggleText(e, papersExpanded))}</button>` : ''}
      </div>
    </div>
    ${papersExpanded ? renderCompactLivePaperPanel(e) : ''}
  </article>`;
}

function posterSessionZoomAnchorId(eventId) {
  const safeId = String(eventId || 'poster').replace(/[^a-zA-Z0-9_-]+/g, '-');
  return `poster-session-zoom-${safeId}`;
}

function renderLivePosterPaperPanel(e) {
  const papers = e?.papers || [];
  if (!papers.length) return '<div class="live-poster-paper-panel empty-card">No poster papers are listed for this session.</div>';
  const sessionZoomUrl = e?.links?.zoom || '';
  return `<div class="live-poster-paper-panel" data-live-poster-panel="${esc(e.id)}">
    <div class="paper-list">${papers.map((paper) => renderPaperCard(paper, { sessionZoomUrl })).join('')}</div>
  </div>`;
}

function renderSessionCard(e) {
  const isSelected = selectedPosterEventId === e.id;
  const zoomLinked = Boolean(e?.links?.zoom);
  const badge = eventBadge(e, `event:${e.id}`);
  return `<article class="event-card poster-session-card${zoomLinked ? ' live-zoom-linked-card' : ''}${isSelected ? ' selected is-paper-expanded' : ''}" data-event-id="${esc(e.id)}" data-poster-id="${esc(e.id)}">
    <div class="live-event-card-body">
      <div class="live-event-header">
        <div class="live-event-title-block">
          ${eventTitleHtml(e, 'card-title live-card-title')}
          ${liveOngoingMeta(e)}
        </div>
        ${badge ? `<div class="live-event-status-stack">${badge}</div>` : ''}
      </div>
      <div class="live-poster-conversation-line"><span class="active-conversation-badge" data-lobby-count>${lobbyCountHtml(e)}</span><span class="active-conversation-badge poster-summary-separator" aria-hidden="true">/</span><span class="active-conversation-badge" data-total-count>${totalCountHtml(e)}</span></div>
      <div class="live-event-actions live-poster-actions">
        ${linkRow(e.links, { showInfo: false, zoomId: e?.links?.zoom ? posterSessionZoomAnchorId(e.id) : '' })}
        <button class="link-button live-session-paper-toggle" type="button" data-live-poster-toggle="${esc(e.id)}" aria-expanded="${isSelected ? 'true' : 'false'}">
          <span aria-hidden="true">${isSelected ? '−' : '+'}</span> ${esc(paperToggleText(e, isSelected))}
        </button>
      </div>
    </div>
    ${isSelected ? renderLivePosterPaperPanel(e) : ''}
  </article>`;
}

function speakerStatusClass(paper, info) {
  return paper.status === 'history' ? 'ended' : paper.status === 'upcoming' ? 'scheduled' : info.disconnected ? 'disconnected' : info.talking ? 'talking' : 'idle';
}

function renderSpeakerBlock(paper) {
  const info = speakerInfo(paper);
  const className = speakerStatusClass(paper, info);
  const headline = info.label;
  return `<span class="speech-block ${className}" data-speaker-status-block>
    <span class="speech-icon" aria-hidden="true"><span class="pixel-speaker-avatar"><i></i><b></b></span></span>
    <span class="speaker-copy">
      <strong data-speaker-headline>${esc(headline)}</strong>
    </span>
  </span>`;
}

function renderPaperCard(p, opts = {}) {
  const detailUrl = detailUrlFromPaper(p);
  const sessionZoomUrl = String(opts.sessionZoomUrl || '');
  const authorsId = `paper-authors-${String(p.id || 'paper').replace(/[^a-zA-Z0-9_-]+/g, '-')}`;
  return `<article class="paper-card live-paper-card" data-paper-id="${esc(p.id)}">
    <div class="paper-card-status-row">
      <div class="paper-id">${esc(p.displayId || p.id)}</div>
      ${paperBadge(p)}
    </div>
    <div class="paper-card-copy">
      <h4 class="paper-title"><a href="${esc(detailUrl)}" target="_blank" rel="noopener">${esc(p.title)}</a></h4>
      <div class="paper-authors-wrap">
        <div class="paper-authors" id="${esc(authorsId)}" data-paper-authors>${esc(p.authors)}</div>
        <button class="paper-authors-toggle" type="button" data-paper-authors-toggle aria-controls="${esc(authorsId)}" aria-expanded="false" hidden>more</button>
      </div>
    </div>
    <div class="paper-card-controls">
      <div class="presenter-mode-row">
        <div class="presenter-mode-line" data-presenter-mode>${presenterLabel(p.presenterMode)}</div>
      </div>
      <div class="speech-row">${renderSpeakerBlock(p)}</div>
      ${paperLinkRow(p, detailUrl, sessionZoomUrl)}
    </div>
  </article>`;
}

// Paper cards: Zoom (the session's room) · Slack · Paper · Poster. Paper and Poster open the
// miniconf paper page at that section (its poster.js opens the section named by the #fragment).
function paperLinkRow(p, detailUrl, sessionZoomUrl) {
  const links = p?.links || {};
  const section = (id, has) => (has && detailUrl ? `${detailUrl}#${id}` : '');
  const buttons = [
    [sessionZoomUrl || links.zoom, 'Zoom'],
    [links.slack, 'Slack'],
    [section('paper', links.pdf), 'Paper'],
    [section('poster', links.poster), 'Poster'],
  ].filter(([url]) => url);
  if (!buttons.length) return '';
  return `<div class="link-row">${buttons.map(([url, label]) => `<a class="link-button" href="${esc(url)}" target="_blank" rel="noopener">${label}</a>`).join('')}</div>`;
}

function syncPaperAuthorOverflow(scope = document) {
  const cards = scope.querySelectorAll ? scope.querySelectorAll('.live-paper-card') : [];
  for (const card of cards) {
    const authors = card.querySelector('[data-paper-authors]');
    const toggle = card.querySelector('[data-paper-authors-toggle]');
    if (!authors || !toggle) continue;
    const expanded = card.classList.contains('authors-expanded');
    if (expanded) {
      toggle.hidden = false;
      continue;
    }
    toggle.hidden = true;
    requestAnimationFrame(() => {
      const overflow = authors.scrollHeight > authors.clientHeight + 1;
      toggle.hidden = !overflow;
    });
  }
}

function groupOverlappingLiveEvents(events) {
  const sorted = [...events].sort((a, b) => {
    const aStart = Date.parse(a.startsAt || '');
    const bStart = Date.parse(b.startsAt || '');
    return aStart - bStart
      || Number(b?.type === 'poster') - Number(a?.type === 'poster')
      || Date.parse(a.endsAt || '') - Date.parse(b.endsAt || '');
  });
  const rows = [];
  let row = null;
  for (const event of sorted) {
    const startMs = Date.parse(event.startsAt || '');
    const endMs = Date.parse(event.endsAt || '');
    if (!row || !Number.isFinite(startMs) || startMs >= row.endMs) {
      row = { endMs: Number.isFinite(endMs) ? endMs : startMs, events: [] };
      rows.push(row);
    }
    row.events.push(event);
    if (Number.isFinite(endMs)) row.endMs = Math.max(row.endMs, endMs);
  }
  for (const group of rows) {
    group.events.sort((a, b) => Number(b?.type === 'poster') - Number(a?.type === 'poster') || byStart(a, b));
  }
  return rows;
}

function renderLiveOverlapRow(group) {
  // Any paper-bearing session (Poster or Oral) owns the full overlap row while expanded.
  // This keeps the disclosure behavior consistent: expand -> hide simultaneous events -> full width.
  const expandedPoster = group.events.find((e) => e.id === selectedPosterEventId && e.type === 'poster') || null;
  const expandedSession = group.events.find((e) => e.type !== 'poster' && expandedLivePaperEventIds.has(e.id)) || null;
  const expanded = expandedPoster || expandedSession;
  const visibleEvents = expanded ? [expanded] : groupTutorialEvents(group.events);
  // Keep a lone live-event card at the same desktop width as one card in a two-event row.
  // Any expanded paper session is the exception: it deliberately owns the full row.
  const columns = expanded || (visibleEvents.length === 1 && visibleEvents[0].tutorials) ? 1 : Math.max(2, visibleEvents.length);
  const expandedClass = expanded ? ` paper-session-expanded${expanded.type === 'poster' ? ' poster-expanded' : ''}` : '';
  return `<div class="live-overlap-row${expandedClass}" style="--live-columns:${columns}" data-live-overlap-row>
    ${visibleEvents.map((e) => e.tutorials ? renderLiveTutorials(e) : e.type === 'poster' ? renderSessionCard(e) : renderEventCard(e)).join('')}
  </div>`;
}

function renderLive(state) {
  if (!els.live || !els.spotlight) return;
  const liveEvents = getLiveEvents(state);
  els.spotlight.innerHTML = '';

  const posterEvents = liveEvents.filter(e => e.type === 'poster');
  if (selectedPosterEventId && !posterEvents.some(e => e.id === selectedPosterEventId)) selectedPosterEventId = null;
  for (const id of [...expandedLivePaperEventIds]) {
    if (!liveEvents.some((e) => e.id === id && sessionHasPapers(e) && e.type !== 'poster')) expandedLivePaperEventIds.delete(id);
  }
  const groups = groupOverlappingLiveEvents(liveEvents);

  document.body.classList.remove('poster-detail-open');
  els.live.innerHTML = `<div class="live-layout is-collapsed">
    <div class="event-list">
      ${groups.length ? groups.map(renderLiveOverlapRow).join('') : '<article class="empty-card">No live events.</article>'}
    </div>
  </div>`;
  syncPaperAuthorOverflow(els.live);
}


function renderUpcomingPaperList(e) {
  const papers = e?.papers || [];
  if (!papers.length) return '<span class="upcoming-paper-count-empty">0 papers</span>';
  const panelId = `upcoming-papers-${String(e.id || 'session').replace(/[^a-zA-Z0-9_-]+/g, '-')}`;
  return `<button class="upcoming-paper-toggle" type="button" aria-expanded="false" aria-controls="${esc(panelId)}" data-upcoming-paper-toggle data-paper-count="${papers.length}">
    ${papers.length} paper${papers.length === 1 ? '' : 's'} · Expand
  </button>
  <div class="upcoming-paper-panel" id="${esc(panelId)}" hidden>
    <ol>
      ${papers.map((paper) => {
        const detailUrl = detailUrlFromPaper(paper);
        const content = `<span class="upcoming-paper-id">${esc(paper.displayId || paper.id)}</span><span class="upcoming-paper-title">${esc(paper.title)}</span>`;
        return `<li>${detailUrl ? `<a href="${esc(detailUrl)}" target="_blank" rel="noopener">${content}</a>` : `<span class="upcoming-paper-static">${content}</span>`}</li>`;
      }).join('')}
    </ol>
  </div>`;
}

function upcomingSecondaryMeta(e) {
  return [e?.venue || 'Venue TBA', e?.topic || ''].filter(Boolean).map(esc).join(' · ');
}

function groupOverlappingUpcomingEvents(events) {
  const sorted = [...events].sort((a, b) => {
    const aStart = Date.parse(a.startsAt || '');
    const bStart = Date.parse(b.startsAt || '');
    return aStart - bStart
      || Number(b?.type === 'poster') - Number(a?.type === 'poster')
      || Date.parse(a.endsAt || '') - Date.parse(b.endsAt || '');
  });
  const rows = [];
  let row = null;
  for (const event of sorted) {
    const startMs = Date.parse(event.startsAt || '');
    const endMs = Date.parse(event.endsAt || '');
    if (!row || !Number.isFinite(startMs) || startMs >= row.endMs) {
      row = { endMs: Number.isFinite(endMs) ? endMs : startMs, events: [] };
      rows.push(row);
    } else if (Number.isFinite(endMs)) {
      row.endMs = Math.max(row.endMs, endMs);
    }
    row.events.push(event);
  }
  for (const item of rows) {
    item.events.sort((a, b) => Number(b?.type === 'poster') - Number(a?.type === 'poster')
      || Date.parse(a.startsAt || '') - Date.parse(b.startsAt || '')
      || String(a.title || '').localeCompare(String(b.title || '')));
  }
  return rows;
}

function renderUpcomingCard(e) {
  const isPoster = e?.type === 'poster';
  const hasPapers = sessionHasPapers(e);
  return `<article class="timeline-item upcoming-completed-card${isPoster ? ' upcoming-poster-card' : ''}" data-event-id="${esc(e.id)}" data-event-type="${esc(e.type || 'event')}">
    <div class="timeline-status-row upcoming-card-time-row">
      <div class="timeline-time upcoming-card-time"><span class="upcoming-clock-icon" aria-hidden="true"><svg viewBox="0 0 16 16" focusable="false"><circle cx="8" cy="8" r="5.75"></circle><path d="M8 4.75v3.6l2.45 1.45"></path></svg></span><time datetime="${esc(e.startsAt)}">${fmtTimelineTime(e.startsAt)}</time><span aria-hidden="true">–</span><time datetime="${esc(e.endsAt)}">${(e.endTimeTBD ? 'TBD' : fmtTimelineTime(e.endsAt))}</time><span class="upcoming-event-timezone">· ${esc(fmtUtcOffset(e.startsAt))}</span></div>
    </div>
    <div class="upcoming-card-title-row">
      ${eventTitleHtml(e, 'card-title upcoming-card-title')}
      ${hasPapers ? renderUpcomingPaperList(e) : ''}
      ${e.tutorials ? '' : upcomingSlackLink(e)}
    </div>
    ${e.tutorials ? tutorialRows(e, false) : ''}
  </article>`;
}

function renderUpcoming(state) {
  if (!els.upcoming) return;
  const upcoming = groupTutorialEvents(getUpcomingEvents(state)).slice(0, 14);
  const groups = [];
  upcoming.forEach((event) => {
    const key = timelineDateKey(event.startsAt);
    let group = groups[groups.length - 1];
    if (!group || group.key !== key) {
      group = { key, startsAt: event.startsAt, events: [] };
      groups.push(group);
    }
    group.events.push(event);
  });

  els.upcoming.innerHTML = upcoming.length
    ? `<div class="timeline upcoming-completed-timeline">${groups.map(group => `<section class="upcoming-completed-day" data-date="${esc(group.key)}">
        <div class="upcoming-completed-date"><span class="upcoming-calendar-icon" aria-hidden="true"><svg viewBox="0 0 16 16" focusable="false"><rect x="2.25" y="3.5" width="11.5" height="10" rx="1.25"></rect><path d="M5 2v3M11 2v3M2.5 6.5h11"></path></svg></span><span>${esc(fmtTimelineDate(group.startsAt))}</span></div>
        ${groupOverlappingUpcomingEvents(group.events).map(row => `<div class="upcoming-overlap-row" style="--upcoming-columns:${Math.max(1, row.events.length)}">
          ${row.events.map(renderUpcomingCard).join('')}
        </div>`).join('')}
      </section>`).join('')}</div>`
    : '<article class="empty-card">No upcoming events remain.</article>';
}

function render(rawState) {
  if (!rawState) return;
  const incomingRevision = clockRevision(rawState);
  if (latestClockRevisionSeen >= 0 && incomingRevision < latestClockRevisionSeen) return;
  latestClockRevisionSeen = Math.max(latestClockRevisionSeen, incomingRevision);
  const state = stateForDisplay(rawState);
  currentState = state;
  conferenceTimeZone = state.conference?.timeZone || conferenceTimeZone;
  window.ISMIRTimeZone?.setReferenceDate?.(debugTimeMs(state));
  lastTopologyKey = topologyKey(state);
  lastClockAuthoritySignature = clockAuthoritySignature(state);
  document.title = debugMode ? 'Conference time control' : (state.conference?.pageTitle || 'What’s going on now');
  renderDebugClock(state);
  if (debugMode) return;
  if (els.lastUpdated) els.lastUpdated.textContent = `Last updated ${relativeTime(state.updatedAt)}`;
  renderDashboard(state);
  renderLive(state);
  renderUpcoming(state);
}

function setConnection(online, label) {
  if (!els.connection) return;
  els.connection.textContent = label || (online ? 'Realtime connected' : 'Offline');
  els.connection.className = `connection ${online ? 'online' : 'offline'}`;
}

function updateZoomBadgeByKey(key, headcounts) {
  const badge = findByAttr(document, 'data-zoom-badge', key);
  if (!badge) return;
  const shown = zoomCountPresentation(headcounts);
  const prefixEl = badge.querySelector('[data-zoom-prefix]');
  const countEl = badge.querySelector('[data-zoom-count]');
  if (prefixEl && prefixEl.textContent !== shown.prefix) prefixEl.textContent = shown.prefix;
  if (countEl && countEl.textContent !== shown.count) countEl.textContent = shown.count;
  if (shown.title) badge.setAttribute('title', shown.title);
  else badge.removeAttribute('title');
}
function updatePeakBadgeByKey(key, metrics) {
  const badge = findByAttr(document, 'data-peak-badge', key);
  if (!badge) return;
  const countEl = badge.querySelector('[data-peak-count]');
  const next = metrics?.available === false ? '—' : String(Number(metrics?.peakZoom || 0));
  if (countEl && countEl.textContent !== next) countEl.textContent = next;
}

function updateSpeakerBlock(card, paper) {
  const block = card.querySelector('[data-speaker-status-block]');
  if (!block) return;
  const info = speakerInfo(paper);
  const statusClass = speakerStatusClass(paper, info);
  for (const c of ['talking', 'connected', 'idle', 'ended', 'scheduled', 'disconnected']) block.classList.toggle(c, c === statusClass);
  const headline = block.querySelector('[data-speaker-headline]');
  const nextHeadline = info.label;
  if (headline && headline.textContent !== nextHeadline) headline.textContent = nextHeadline;
}

function updatePaperCard(paper) {
  const card = findByAttr(document, 'data-paper-id', paper.id);
  if (!card) return;
  if (paper.status === 'live') updateZoomBadgeByKey(`paper:${paper.id}`, paper.headcounts);
  if (paper.status === 'history') updatePeakBadgeByKey(`paper:${paper.id}`, paper.metrics);
  const mode = card.querySelector('[data-presenter-mode]');
  const nextMode = presenterLabel(paper.presenterMode);
  if (mode && mode.textContent !== nextMode) mode.textContent = nextMode;
  updateSpeakerBlock(card, paper);
}

function updateEventCard(event) {
  if (event.status === 'live') updateZoomBadgeByKey(`event:${event.id}`, event.headcounts);
  if (event.status === 'history') updatePeakBadgeByKey(`event:${event.id}`, event.metrics);
  const card = findByAttr(document, 'data-event-id', event.id);
  const lobby = card?.querySelector('[data-lobby-count]');
  if (lobby) lobby.innerHTML = lobbyCountHtml(event);
  const total = card?.querySelector('[data-total-count]');
  if (total) total.innerHTML = totalCountHtml(event);
}

function totalCountHtml(event) {
  const shown = zoomCountPresentation(event.headcounts);
  return `<strong>${esc(shown.prefix + shown.count)}</strong> ${shown.count === '1' ? 'attendee' : 'attendees'} online in total`;
}

function lobbyCountHtml(event) {
  const count = event.headcounts?.available === false ? '?' : Number(event.headcounts?.lobbyZoom || 0);
  return `<strong>${esc(count)}</strong> ${count === 1 ? 'attendee' : 'attendees'} in the lobby`;
}

function patchRealtimeState(nextRawState) {
  const incomingRevision = clockRevision(nextRawState);
  if (latestClockRevisionSeen >= 0 && incomingRevision < latestClockRevisionSeen) return;
  const nextState = stateForDisplay(nextRawState);
  if (!currentState) return render(nextRawState);
  conferenceTimeZone = nextState.conference?.timeZone || conferenceTimeZone;
  const nextTopology = topologyKey(nextState);
  const nextClockSignature = clockAuthoritySignature(nextState);
  const clockAuthorityChanged = nextClockSignature !== lastClockAuthoritySignature;
  if (nextTopology !== lastTopologyKey || clockAuthorityChanged) return render(nextRawState);
  latestClockRevisionSeen = Math.max(latestClockRevisionSeen, incomingRevision);
  currentState = nextState;
  window.ISMIRTimeZone?.setReferenceDate?.(debugTimeMs(nextState));
  lastClockAuthoritySignature = nextClockSignature;
  document.title = nextState.conference?.pageTitle || 'What’s going on now';
  if (els.lastUpdated) els.lastUpdated.textContent = `Last updated ${relativeTime(nextState.updatedAt)}`;
  renderDebugClock(nextState);
  updateDashboard(nextState);
  for (const event of getLiveEvents(nextState)) updateEventCard(event);
  for (const paper of getAllPosterPapers(nextState)) updatePaperCard(paper);
}

function queueRealtimeState(nextState) {
  if (!nextState) return;
  const incomingRevision = clockRevision(nextState);
  if (latestClockRevisionSeen >= 0 && incomingRevision < latestClockRevisionSeen) return;
  if (pendingRealtimeState && clockRevision(pendingRealtimeState) > incomingRevision) return;
  pendingRealtimeState = nextState;
  if (realtimeUpdateQueued) return;
  realtimeUpdateQueued = true;
  requestAnimationFrame(() => {
    realtimeUpdateQueued = false;
    const stateToApply = pendingRealtimeState;
    pendingRealtimeState = null;
    if (stateToApply) patchRealtimeState(stateToApply);
  });
}

function restoreInitialHashAfterRender() {
  const hash = String(location.hash || '').replace(/^#/, '');
  if (!hash) return;
  const target = document.getElementById(hash);
  if (!target) return;
  requestAnimationFrame(() => requestAnimationFrame(() => {
    target.scrollIntoView({ block: 'start', behavior: 'auto' });
  }));
}

async function fetchStateAtClockRevision(minRevision) {
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const url = `/api/state?_clock=${encodeURIComponent(String(minRevision))}&_=${Date.now()}`;
    const stateRes = await fetch(url, { cache: 'no-store', credentials: 'same-origin' });
    const stateData = await stateRes.json();
    if (stateRes.ok && stateData?.ok && stateData.state && clockRevision(stateData.state) >= minRevision) return stateData.state;
    if (attempt === 0) await new Promise((resolve) => setTimeout(resolve, 180));
  }
  return null;
}

async function refreshClockAuthorityFallback() {
  if (publicStatic || debugMode || clockAuthorityPollBusy || !currentState) return;
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

    // Last-resort visual fallback: use the new clock authority with the most
    // recent event payload, and keep the signature dirty so the next poll
    // retries the authoritative state fetch instead of getting stuck.
    const mergedState = {
      ...currentState,
      debugClock: clockData.debugClock,
      serverNow: clockData.debugClock.serverNow || currentState.serverNow,
    };
    render(mergedState);
    lastClockAuthoritySignature = '';
  } catch (_) {
    // WebSocket remains the primary realtime transport. This poll is only a
    // clock-authority fallback, so transient failures are intentionally quiet.
  } finally {
    clockAuthorityPollBusy = false;
  }
}

async function fetchInitial() {
  if (publicStatic) {
    let restoredHash = false;
    window.ISMIRPublic.start({ ...window.ISMIR_PUBLIC_CONFIG,
      onStatus: setConnection,
      onState: state => {
        state = window.ISMIRSite?.localizeState(state) || state;
        latestClockRevisionSeen = -1; pendingRealtimeState = null;
        if (!currentState || state.scheduleRevision !== currentState.scheduleRevision || Boolean(state.offline) !== Boolean(currentState.offline)) render(state);
        else patchRealtimeState(state);
        if (!restoredHash && state.events.length) { restoredHash = true; restoreInitialHashAfterRender(); }
      },
    });
    return;
  }
  if (debugMode) {
    try {
      const stateRes = await fetch('/api/state', { cache: 'no-store' });
      const stateData = await stateRes.json();
      if (stateData.ok && stateData.state) {
        conferenceTimeZone = stateData.state?.conference?.timeZone || conferenceTimeZone;
        currentState = stateData.state;
      }
    } catch (_) {}
    if (await applyInitialDebugNowParam()) {}
    await refreshDebugClockPanel();
    return;
  }
  const res = await fetch('/api/state', { cache: 'no-store' });
  const data = await res.json();
  if (data.ok) {
    conferenceTimeZone = data.state?.conference?.timeZone || conferenceTimeZone;
    render(data.state);
    restoreInitialHashAfterRender();
  }
}
function connectWS() {
  if (publicStatic || debugMode) return;
  clearTimeout(reconnectTimer);
  const proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${proto}//${location.host}/ws/public`);
  ws.onopen = () => setConnection(true, 'Realtime connected');
  ws.onmessage = (event) => { const msg = JSON.parse(event.data); if (msg.type === 'state') queueRealtimeState(msg.state); };
  ws.onclose = () => { setConnection(false, 'Reconnecting…'); reconnectTimer = setTimeout(connectWS, 1500); };
  ws.onerror = () => setConnection(false, 'Connection issue');
}
function closePosterDetail() {
  selectedPosterEventId = null;
  document.body.classList.remove('poster-detail-open');
  if (currentState) renderLive(currentState);
}
function togglePosterDetail(eventId) {
  selectedPosterEventId = selectedPosterEventId === eventId ? null : eventId;
  if (currentState) renderLive(currentState);
}

if (els.upcoming) {
  els.upcoming.addEventListener('click', (event) => {
    const button = event.target.closest('[data-upcoming-paper-toggle]');
    if (!button) return;
    const panelId = button.getAttribute('aria-controls');
    const panel = panelId ? document.getElementById(panelId) : null;
    if (!panel) return;
    const opening = panel.hidden;
    const card = button.closest('.upcoming-completed-card');
    const row = button.closest('.upcoming-overlap-row');
    panel.hidden = !opening;
    button.setAttribute('aria-expanded', opening ? 'true' : 'false');
    const paperCount = Number(button.dataset.paperCount || 0);
    button.textContent = `${paperCount} paper${paperCount === 1 ? '' : 's'} · ${opening ? 'Collapse' : 'Expand'}`;
    if (card) card.classList.toggle('is-paper-expanded', opening);
    if (row) row.classList.toggle('poster-expanded', opening);
  });
}

if (els.copyLlmPrompt) els.copyLlmPrompt.addEventListener('click', copyLlmPrompt);
if (els.debugClockForm) els.debugClockForm.addEventListener('submit', setDebugClockFromForm);
if (els.debugClockReset) els.debugClockReset.addEventListener('click', resetDebugClock);

if (els.live) {
  els.live.addEventListener('click', (event) => {
    const authorsToggle = event.target.closest('[data-paper-authors-toggle]');
    if (authorsToggle) {
      const card = authorsToggle.closest('.live-paper-card');
      if (!card) return;
      const opening = !card.classList.contains('authors-expanded');
      card.classList.toggle('authors-expanded', opening);
      authorsToggle.setAttribute('aria-expanded', opening ? 'true' : 'false');
      authorsToggle.textContent = opening ? 'less' : 'more';
      if (!opening) syncPaperAuthorOverflow(card.parentElement || els.live);
      return;
    }
    const sessionPaperToggle = event.target.closest('[data-live-session-paper-toggle]');
    if (sessionPaperToggle) {
      const eventId = sessionPaperToggle.dataset.liveSessionPaperToggle;
      if (expandedLivePaperEventIds.has(eventId)) expandedLivePaperEventIds.delete(eventId);
      else expandedLivePaperEventIds.add(eventId);
      if (currentState) renderLive(currentState);
      return;
    }
    const toggle = event.target.closest('[data-live-poster-toggle]');
    if (!toggle) return;
    togglePosterDetail(toggle.dataset.livePosterToggle);
  });
}



// v8.84 hidden Canon-in-D piano easter egg. Deliberately no visible hint.
const CANON_EGG_SEQUENCE = ['D', 'A', 'B', 'F', 'G', 'D', 'G', 'A'];
const CANON_EGG_DEGREE_TO_KEY = { '1': 'D', '5': 'A', '6': 'B', '3': 'F', '4': 'G' };
const CANON_EGG_CHORDS = {
  D: { visual: ['D', 'F#', 'A'], midi: [62, 66, 69] },
  A: { visual: ['C#', 'E', 'A'], midi: [57, 61, 64] },
  B: { visual: ['D', 'F#', 'B'], midi: [59, 62, 66] }, // Bm
  F: { visual: ['C#', 'F#', 'A'], midi: [54, 57, 61] }, // F#m
  G: { visual: ['D', 'G', 'B'], midi: [55, 59, 62] },
};
const CANON_EGG_ROOT_NOTE_TO_KEY = { D: 'D', A: 'A', B: 'B', 'F#': 'F', G: 'G' };
const CANON_EGG_NOTE_GEOMETRY = {
  'C#': { x: 12, width: 8, height: 16, black: true },
  D: { x: 16, width: 15, height: 24, black: false },
  E: { x: 32, width: 15, height: 24, black: false },
  'F#': { x: 60, width: 8, height: 16, black: true },
  G: { x: 64, width: 15, height: 24, black: false },
  A: { x: 80, width: 15, height: 24, black: false },
  B: { x: 96, width: 15, height: 24, black: false },
};
let canonEggAudioContext = null;
let canonEggMaster = null;
let canonEggProgress = 0;
let canonEggCompleted = false;
let canonEggPianoOverlay = null;
let canonEggPointerKey = '';
let canonEggPointerId = null;
let canonEggBinaryGroups = [];
const canonEggHeldKeys = new Set();

function canonEggAudio() {
  const AudioCtor = window.AudioContext || window.webkitAudioContext;
  if (!AudioCtor) return null;
  if (!canonEggAudioContext) {
    try {
      canonEggAudioContext = new AudioCtor();
      canonEggMaster = canonEggAudioContext.createGain();
      canonEggMaster.gain.value = 0.72;
      const compressor = canonEggAudioContext.createDynamicsCompressor();
      compressor.threshold.value = -18;
      compressor.knee.value = 18;
      compressor.ratio.value = 5;
      compressor.attack.value = 0.004;
      compressor.release.value = 0.18;
      canonEggMaster.connect(compressor);
      compressor.connect(canonEggAudioContext.destination);
    } catch (_) { return null; }
  }
  if (canonEggAudioContext.state === 'suspended') canonEggAudioContext.resume().catch(() => {});
  return canonEggAudioContext;
}

function canonEggMidiFrequency(midi) {
  return 440 * Math.pow(2, (Number(midi) - 69) / 12);
}

function canonEggPianoNote(midi, when, duration = 1.05, velocity = 0.11) {
  const ctx = canonEggAudio();
  if (!ctx || !canonEggMaster) return;
  const start = Math.max(ctx.currentTime, Number(when) || ctx.currentTime);
  const end = start + Math.max(0.2, duration);
  const frequency = canonEggMidiFrequency(midi);
  const filter = ctx.createBiquadFilter();
  const envelope = ctx.createGain();
  filter.type = 'lowpass';
  filter.frequency.setValueAtTime(Math.min(5200, 2400 + frequency * 5), start);
  filter.frequency.exponentialRampToValueAtTime(Math.max(900, frequency * 3), end);
  filter.Q.value = 0.35;
  envelope.gain.setValueAtTime(0.0001, start);
  envelope.gain.exponentialRampToValueAtTime(Math.max(0.001, velocity), start + 0.007);
  envelope.gain.exponentialRampToValueAtTime(Math.max(0.0005, velocity * 0.30), start + 0.09);
  envelope.gain.exponentialRampToValueAtTime(0.0001, end);
  envelope.connect(filter);
  filter.connect(canonEggMaster);
  const partials = [[1, 'triangle', 1.0, 0], [2, 'sine', .24, 1.3], [3, 'sine', .10, -1.8], [4, 'sine', .045, 2.4]];
  partials.forEach(([ratio, type, level, detune]) => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(frequency * ratio, start);
    osc.detune.setValueAtTime(detune, start);
    gain.gain.value = level;
    osc.connect(gain); gain.connect(envelope);
    osc.start(start); osc.stop(end + .04);
  });
}

function canonEggPlayChord(key, when = null, options = {}) {
  const ctx = canonEggAudio();
  const chord = CANON_EGG_CHORDS[key];
  if (!ctx || !chord) return;
  const start = when == null ? ctx.currentTime + .005 : when;
  const duration = options.duration || 1.05;
  const velocity = options.velocity || .105;
  const spread = options.spread == null ? .014 : options.spread;
  chord.midi.forEach((midi, index) => canonEggPianoNote(midi, start + index * spread, duration, velocity * (index === 0 ? 1 : .88)));
}

function canonEggPlaySuccessPhrase() {
  const ctx = canonEggAudio();
  if (!ctx) return;
  const start = ctx.currentTime + .12;
  const beat = .42;
  const bass = [50, 45, 47, 42, 43, 50, 43, 45];
  const upper = [
    [62,66,69], [61,64,69], [62,66,71], [61,66,69],
    [62,67,71], [62,66,69], [62,67,71], [61,64,69],
  ];
  upper.forEach((notes, step) => {
    const t = start + step * beat;
    canonEggPianoNote(bass[step], t, beat * 1.5, .075);
    notes.forEach((midi, index) => canonEggPianoNote(midi + 12, t + index * (beat / 4), beat * .95, .072));
  });
  const resolve = start + upper.length * beat;
  [50, 62, 66, 69, 74].forEach((midi, index) => canonEggPianoNote(midi, resolve + index * .04, 1.55, index === 0 ? .08 : .068));
}

function canonEggCreatePianoOverlay() {
  const hero = document.querySelector('.home-hero .hero-copy');
  if (!hero || canonEggPianoOverlay) return;
  const overlay = document.createElement('div');
  overlay.className = 'canon-egg-piano-overlay';
  overlay.setAttribute('aria-hidden', 'true');
  Object.entries(CANON_EGG_NOTE_GEOMETRY).forEach(([note, geometry]) => {
    const node = document.createElement('i');
    node.className = `canon-egg-piano-key ${geometry.black ? 'black' : 'white'}`;
    node.dataset.canonNote = note;
    const chordKey = CANON_EGG_ROOT_NOTE_TO_KEY[note];
    if (chordKey) {
      node.dataset.canonRoot = chordKey;
      node.classList.add('is-root-trigger');
    }
    overlay.appendChild(node);
  });
  hero.appendChild(overlay);
  canonEggPianoOverlay = overlay;
  canonEggLayoutPiano();
}

function canonEggLayoutPiano() {
  if (!canonEggPianoOverlay) return;
  const width = canonEggPianoOverlay.clientWidth;
  if (!width) return;
  const octaveWidth = 112;
  const maxStart = Math.max(0, width - octaveWidth);
  let octaveStart = Math.round((width / 2 - octaveWidth / 2) / octaveWidth) * octaveWidth;
  octaveStart = Math.max(0, Math.min(maxStart, octaveStart));
  Object.entries(CANON_EGG_NOTE_GEOMETRY).forEach(([note, geometry]) => {
    const node = canonEggPianoOverlay.querySelector(`[data-canon-note="${note}"]`);
    if (!node) return;
    node.style.left = `${octaveStart + geometry.x}px`;
    node.style.width = `${geometry.width}px`;
    node.style.height = `${geometry.height}px`;
  });
}

function canonEggRenderPressedKeys() {
  if (!canonEggPianoOverlay) return;
  const activeNotes = new Set();
  canonEggHeldKeys.forEach((key) => (CANON_EGG_CHORDS[key]?.visual || []).forEach((note) => activeNotes.add(note)));
  canonEggPianoOverlay.querySelectorAll('[data-canon-note]').forEach((node) => node.classList.toggle('is-pressed', activeNotes.has(node.dataset.canonNote)));
}

function canonEggRenderProgress() {
  canonEggBinaryGroups.forEach((group, index) => group.classList.toggle('canon-egg-lit', index < canonEggProgress));
}

function canonEggPaperPool() {
  const seen = new Set();
  const pool = [];
  for (const event of currentState?.events || []) {
    for (const paper of event?.papers || []) {
      // Oral and poster sessions list the same paper under different ids; dedupe by source paper.
      const id = String(paper?.sourcePaperId || paper?.id || paper?.title || '').trim();
      if (!id || seen.has(id)) continue;
      seen.add(id);
      // Only papers with an author-provided fun fact are eligible.
      const fact = String(paper?.funFact || '').trim();
      if (fact) pool.push({ id, title: String(paper?.title || id), fact });
    }
  }
  return pool;
}

function canonEggCloseFunFact() {
  document.querySelector('.canon-egg-funfact-backdrop')?.remove();
  canonEggCompleted = false;
  canonEggProgress = 0;
  canonEggRenderProgress();
}

function canonEggShowFunFact() {
  const pool = canonEggPaperPool();
  // No fun facts yet: reset so the puzzle can be played again instead of staying "completed".
  if (!pool.length) { canonEggCloseFunFact(); return; }
  const paper = pool[Math.floor(Math.random() * pool.length)];
  const backdrop = document.createElement('div');
  backdrop.className = 'canon-egg-funfact-backdrop';
  backdrop.innerHTML = `<section class="canon-egg-funfact-dialog" role="dialog" aria-modal="true" aria-labelledby="canon-egg-title">
    <span class="canon-egg-funfact-kicker">Paper fun fact</span>
    <h3 id="canon-egg-title"></h3>
    <p class="canon-egg-funfact-copy"></p>
    <button class="canon-egg-funfact-close" type="button">Close</button>
  </section>`;
  backdrop.querySelector('#canon-egg-title').textContent = paper.title;
  backdrop.querySelector('.canon-egg-funfact-copy').textContent = paper.fact;
  const close = backdrop.querySelector('.canon-egg-funfact-close');
  close.addEventListener('click', canonEggCloseFunFact);
  backdrop.addEventListener('click', (event) => { if (event.target === backdrop) canonEggCloseFunFact(); });
  document.body.appendChild(backdrop);
  requestAnimationFrame(() => backdrop.classList.add('is-visible'));
  close.focus({ preventScroll: true });
}

function canonEggAdvance(key) {
  if (canonEggCompleted) return;
  if (CANON_EGG_SEQUENCE[canonEggProgress] === key) {
    canonEggProgress += 1;
    canonEggRenderProgress();
    if (canonEggProgress === CANON_EGG_SEQUENCE.length) {
      canonEggCompleted = true;
      canonEggPlaySuccessPhrase();
      canonEggShowFunFact();
    }
    return;
  }
  // Strict reset: a wrong mapped chord turns every progress light off and the
  // next chord starts a new attempt.
  canonEggProgress = 0;
  canonEggRenderProgress();
}

// Keep native new-tab anchors for keyboard/context-menu use and blocked popups.
// A plain primary click also requests focus; the browser owns the final tab policy.
function handleZoomTabClick(event) {
  if (event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey) return;
  const anchor = event.target.closest?.('a[href]');
  if (!anchor || anchor.target !== '_blank') return;
  let url;
  try { url = new URL(anchor.href, window.location.href); } catch (_) { return; }
  if (!window.ISMIRSite.isZoomRedirectUrl(url)) return;
  let tab;
  try {
    // No window features: request a normal browsing tab, not a sized popup.
    // Detach the opener before navigating to an external site.
    tab = window.open('about:blank', '_blank');
    if (!tab) return;
    tab.opener = null;
    tab.location.replace(url.href);
  } catch (_) {
    try { tab?.close(); } catch (_) {}
    return; // The unprevented native anchor remains the fallback.
  }
  event.preventDefault();
  try { tab.focus(); } catch (_) {}
}
document.addEventListener('click', handleZoomTabClick);

function canonEggEditableTarget(target) {
  if (!(target instanceof Element)) return false;
  return Boolean(target.closest('input, textarea, select, [contenteditable="true"]'));
}

function canonEggKeyboardChord(event) {
  const codeMatch = /^Key([DABFG])$/.exec(String(event.code || ''));
  const keyText = String(event.key || '').toUpperCase();
  // event.key supports both the number row and NumLock-enabled number pad,
  // without interpreting navigation keys or shifted punctuation as notes.
  return codeMatch?.[1] || (['D', 'A', 'B', 'F', 'G'].includes(keyText) ? keyText : CANON_EGG_DEGREE_TO_KEY[keyText] || '');
}

function canonEggKeyDown(event) {
  if (debugMode || event.isComposing || event.repeat || event.ctrlKey || event.metaKey || event.altKey || canonEggEditableTarget(event.target)) return;
  const key = canonEggKeyboardChord(event);
  if (!key) return;
  canonEggHeldKeys.add(key);
  canonEggRenderPressedKeys();
  canonEggPlayChord(key);
  canonEggAdvance(key);
}

function canonEggKeyUp(event) {
  const key = canonEggKeyboardChord(event);
  if (!key) return;
  canonEggHeldKeys.delete(key);
  canonEggRenderPressedKeys();
}

function canonEggPointerDown(event) {
  if (debugMode || canonEggCompleted) return;
  const root = event.target.closest?.('[data-canon-root]');
  if (!root || !canonEggPianoOverlay?.contains(root)) return;
  const key = root.dataset.canonRoot || '';
  if (!CANON_EGG_CHORDS[key]) return;
  event.preventDefault();
  canonEggPointerKey = key;
  canonEggPointerId = event.pointerId;
  try { root.setPointerCapture?.(event.pointerId); } catch (_) {}
  canonEggHeldKeys.add(key);
  canonEggRenderPressedKeys();
  canonEggPlayChord(key);
  canonEggAdvance(key);
}

function canonEggPointerUp(event) {
  if (!canonEggPointerKey) return;
  if (canonEggPointerId != null && event.pointerId != null && event.pointerId !== canonEggPointerId) return;
  canonEggHeldKeys.delete(canonEggPointerKey);
  canonEggPointerKey = '';
  canonEggPointerId = null;
  canonEggRenderPressedKeys();
}

function initCanonEasterEgg() {
  if (debugMode) return;
  canonEggCreatePianoOverlay();
  canonEggBinaryGroups = [...document.querySelectorAll('.llm-prompt-card .binary-puzzle .bit-group')].slice(0, CANON_EGG_SEQUENCE.length);
  canonEggRenderProgress();
  window.addEventListener('keydown', canonEggKeyDown);
  window.addEventListener('keyup', canonEggKeyUp);
  canonEggPianoOverlay?.addEventListener('pointerdown', canonEggPointerDown);
  window.addEventListener('pointerup', canonEggPointerUp);
  window.addEventListener('pointercancel', canonEggPointerUp);
  window.addEventListener('blur', () => {
    canonEggHeldKeys.clear();
    canonEggPointerKey = '';
    canonEggPointerId = null;
    canonEggRenderPressedKeys();
  });
}

initCanonEasterEgg();

window.addEventListener('ismir-timezone-change', () => {
  if (!currentState) return;
  if (debugMode) renderDebugClock(currentState);
  else render(currentState);
});

fetchInitial().catch(() => setConnection(false, 'Initial load failed'));
connectWS();
if (debugMode) {
  debugClockPollTimer = setInterval(refreshDebugClockPanel, 1000);
} else {
  setInterval(() => {
    if (!currentState) return;
    if (els.lastUpdated) els.lastUpdated.textContent = `Last updated ${relativeTime(currentState.updatedAt)}`;
    updateDashboard(stateForDisplay(currentState));
  }, 5000);
  setInterval(refreshClockAuthorityFallback, 2000);
  window.addEventListener('focus', refreshClockAuthorityFallback);
  document.addEventListener('visibilitychange', () => {
    if (!document.hidden) refreshClockAuthorityFallback();
  });
}
window.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  if (document.querySelector('.canon-egg-funfact-backdrop')) canonEggCloseFunFact();
  else if (selectedPosterEventId) closePosterDetail();
});
window.addEventListener('resize', () => {
  if (els.live) syncPaperAuthorOverflow(els.live);
  canonEggLayoutPiano();
});
