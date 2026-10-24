'use strict';
// The live page: what is on now, the dashboard, and what comes next. Data comes from the live
// overview's backend through public-connection.js; overview-common.js has the shared helpers.

const els = {
  connection: document.getElementById('connection-status'),
  dashboard: document.getElementById('dashboard-grid'),
  live: document.getElementById('live-events-root'),
  upcoming: document.getElementById('upcoming-events-root'),
  copyLlmPrompt: document.getElementById('copy-llm-prompt'),
  copyLlmStatus: document.getElementById('llm-copy-status'),
};

let currentState = null;
let selectedPosterEventId = null;
const expandedLivePaperEventIds = new Set();
let lastTopologyKey = '';
let lastClockSignature = '';

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
  const now = state ? conferenceNow(state) : Date.now();
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

function fmtShortDate(iso) {
  if (!iso) return '—';
  return new Intl.DateTimeFormat('en', { month: 'short', day: '2-digit', timeZone: displayTimeZone() }).format(new Date(iso));
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

function eventTitleHtml(e, className = 'card-title') {
  const url = eventInfoUrl(e);
  const title = esc(e.title);
  return url
    ? `<h3 class="${className}"><a href="${esc(url)}" target="_blank" rel="noopener">${title}</a></h3>`
    : `<h3 class="${className}">${title}</h3>`;
}

function linkRow(links, opts = {}) {
  const safe = links || {};
  const showInfo = opts.showInfo !== false;
  const infoUrl = opts.infoUrl || safe.info || safe.detail || '';
  return `<div class="link-row">
    ${showInfo && infoUrl ? `<a class="link-button info-link" href="${esc(infoUrl)}" target="_blank" rel="noopener">Info</a>` : ''}
    ${safe.slack ? `<a class="link-button" href="${esc(safe.slack)}" target="_blank" rel="noopener">Slack</a>` : ''}
    ${safe.zoom ? `<a class="link-button" href="${esc(safe.zoom)}" target="_blank" rel="noopener">Zoom</a>` : ''}
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
  const display = stateAtConferenceTime(state || currentState || { events: [] });
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
        ${linkRow(e.links, { showInfo: false })}
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
  if (!els.live) return;
  const liveEvents = getLiveEvents(state);

  const posterEvents = liveEvents.filter(e => e.type === 'poster');
  if (selectedPosterEventId && !posterEvents.some(e => e.id === selectedPosterEventId)) selectedPosterEventId = null;
  for (const id of [...expandedLivePaperEventIds]) {
    if (!liveEvents.some((e) => e.id === id && sessionHasPapers(e) && e.type !== 'poster')) expandedLivePaperEventIds.delete(id);
  }
  const groups = groupOverlappingLiveEvents(liveEvents);
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

// Upcoming days after tomorrow start folded (the list runs to the end of the conference); a day
// the visitor opens or folds stays that way across updates.
const upcomingDayOpen = new Map();
const DAY_MS = 24 * 60 * 60 * 1000;
function upcomingDayIsOpen(key, state) {
  if (upcomingDayOpen.has(key)) return upcomingDayOpen.get(key);
  return key <= timelineDateKey(new Date(conferenceNow(state) + DAY_MS).toISOString());
}

function setUpcomingDayOpen(head, open) {
  const day = head.closest('.upcoming-completed-day');
  upcomingDayOpen.set(day.dataset.date, open);
  head.setAttribute('aria-expanded', String(open));
  day.classList.toggle('is-folded', !open);
  day.querySelector('.upcoming-day-events').hidden = !open;
  head.querySelector('.upcoming-day-action').textContent = open ? 'Hide' : 'Show';
}

function renderUpcoming(state) {
  if (!els.upcoming) return;
  // Every upcoming event, to the end of the conference: a cut-off list would leave people
  // wondering whether anything comes after it.
  const upcoming = groupTutorialEvents(getUpcomingEvents(state));
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
    ? `<div class="timeline upcoming-completed-timeline">${groups.map((group) => {
      const open = upcomingDayIsOpen(group.key, state);
      const count = group.events.reduce((n, e) => n + (e.tutorials?.length || 1), 0);
      const panelId = `upcoming-day-${group.key}`;
      // A div, not a <button>: the bare-button styles of this sheet would restyle the heading.
      return `<section class="upcoming-completed-day${open ? '' : ' is-folded'}" data-date="${esc(group.key)}">
        <div class="upcoming-completed-date upcoming-day-toggle" role="button" tabindex="0" aria-expanded="${open}" aria-controls="${esc(panelId)}" data-upcoming-day-toggle><span class="upcoming-calendar-icon" aria-hidden="true"><svg viewBox="0 0 16 16" focusable="false"><rect x="2.25" y="3.5" width="11.5" height="10" rx="1.25"></rect><path d="M5 2v3M11 2v3M2.5 6.5h11"></path></svg></span><span>${esc(fmtTimelineDate(group.startsAt))}</span><span class="upcoming-day-count">${count} event${count === 1 ? '' : 's'}</span><span class="upcoming-day-action">${open ? 'Hide' : 'Show'}</span></div>
        <div class="upcoming-day-events" id="${esc(panelId)}"${open ? '' : ' hidden'}>
        ${groupOverlappingUpcomingEvents(group.events).map(row => `<div class="upcoming-overlap-row" style="--upcoming-columns:${Math.max(1, row.events.length)}">
          ${row.events.map(renderUpcomingCard).join('')}
        </div>`).join('')}
        </div>
      </section>`;
    }).join('')}</div>`
    : '<article class="empty-card">No upcoming events remain.</article>';
}

/** The tab title; live-debug.html keeps its [DEBUG] mark. */
function pageTitle(state) {
  return (window.ISMIRChannel === 'debug' ? '[DEBUG] ' : '') + (state.conference?.pageTitle || 'What’s going on now');
}

/** live-debug.html's banner (features.js): the time this page is showing. */
function showDebugClock(state) {
  const node = document.querySelector('[data-debug-clock]');
  if (!node) return;
  node.textContent = testClockApplies(state)
    ? `Test clock: ${new Date(conferenceNow(state)).toLocaleString('en-GB', { timeZone: displayTimeZone(), dateStyle: 'medium', timeStyle: 'short' })} (${displayTimeZone()})`
    : 'Real time (no test clock set)';
}

function render(rawState) {
  if (!rawState) return;
  const state = stateAtConferenceTime(rawState);
  currentState = state;
  window.ISMIRTimeZone?.setReferenceDate?.(conferenceNow(state));
  showDebugClock(state);
  lastTopologyKey = topologyKey(state);
  lastClockSignature = clockSignature(state);
  document.title = pageTitle(state);
  renderDashboard(state);
  renderLive(state);
  renderUpcoming(state);
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

/** A live update with the same events: patch counts and speakers in place (no re-render, no flicker). */
function patchRealtimeState(nextRawState) {
  const nextState = stateAtConferenceTime(nextRawState);
  if (!currentState) return render(nextRawState);
  // New events, a status change or a re-set test clock: render everything again.
  if (topologyKey(nextState) !== lastTopologyKey || clockSignature(nextState) !== lastClockSignature) return render(nextRawState);
  currentState = nextState;
  window.ISMIRTimeZone?.setReferenceDate?.(conferenceNow(nextState));
  document.title = pageTitle(nextState);
  updateDashboard(nextState);
  for (const event of getLiveEvents(nextState)) updateEventCard(event);
  for (const paper of getAllPosterPapers(nextState)) updatePaperCard(paper);
}

function closePosterDetail() {
  selectedPosterEventId = null;
  if (currentState) renderLive(currentState);
}
function togglePosterDetail(eventId) {
  selectedPosterEventId = selectedPosterEventId === eventId ? null : eventId;
  if (currentState) renderLive(currentState);
}

if (els.upcoming) {
  els.upcoming.addEventListener('keydown', (event) => {
    const head = event.target.closest?.('[data-upcoming-day-toggle]');
    if (!head || (event.key !== 'Enter' && event.key !== ' ')) return;
    event.preventDefault();
    setUpcomingDayOpen(head, head.getAttribute('aria-expanded') !== 'true');
  });
  els.upcoming.addEventListener('click', (event) => {
    const head = event.target.closest('[data-upcoming-day-toggle]');
    if (head) { setUpcomingDayOpen(head, head.getAttribute('aria-expanded') !== 'true'); return; }
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

if (els.copyLlmPrompt) els.copyLlmPrompt.addEventListener('click', () => copyPrompt(els.copyLlmPrompt, els.copyLlmStatus, () => buildLlmAttendancePrompt(currentState)));

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



// The Canon easter egg (hidden piano on the hero) lives in canon-egg.js, shared with the Warm-up
// Discussion; egg-account.js signs attendees in for it. This page only says which papers have a
// fun fact.
window.PC_EGG_POOL = () => {
  const seen = new Set();
  const pool = [];
  for (const event of currentState?.events || []) {
    for (const paper of event?.papers || []) {
      // Oral and poster sessions list the same paper under different ids; dedupe by source paper.
      const id = String(paper?.sourcePaperId || paper?.id || paper?.title || '').trim();
      if (!id || seen.has(id)) continue;
      seen.add(id);
      // Only papers with an author-provided fun fact are eligible ("NA" and the like are not facts).
      const fact = String(paper?.funFact || '').trim();
      if (!/^(n\/?a\.?|none|nil|-+)?$/i.test(fact)) pool.push({ id, title: String(paper?.title || id), fact, url: detailUrlFromPaper(paper) });
    }
  }
  return pool;
};

window.addEventListener('ismir-timezone-change', () => { if (currentState) render(currentState); });

// Start: the schedule and live counts (public-connection.js). A changed schedule or going offline
// renders everything; other updates only patch counts and speakers.
let restoredHash = false;
window.ISMIRPublic.start({
  ...window.ISMIR_PUBLIC_CONFIG,
  onStatus: (online, label) => setConnectionStatus(els.connection, online, label),
  onState: state => {
    state = window.ISMIRSite?.localizeState(state) || state;
    if (!currentState || state.scheduleRevision !== currentState.scheduleRevision || Boolean(state.offline) !== Boolean(currentState.offline)) render(state);
    else patchRealtimeState(state);
    // A link to a section (#upcoming-events) lands there once the events are on the page.
    if (!restoredHash && state.events.length && location.hash) {
      restoredHash = true;
      const target = document.getElementById(location.hash.slice(1));
      if (target) requestAnimationFrame(() => requestAnimationFrame(() => target.scrollIntoView({ block: 'start', behavior: 'auto' })));
    }
  },
});
// Keep "next event in N min" current between updates.
setInterval(() => { if (currentState) updateDashboard(stateAtConferenceTime(currentState)); }, 5000);
window.addEventListener('keydown', (event) => {
  if (event.key !== 'Escape') return;
  if (document.querySelector('.canon-egg-funfact-backdrop')) return;   // canon-egg.js closes it
  if (selectedPosterEventId) closePosterDetail();
});
window.addEventListener('resize', () => {
  if (els.live) syncPaperAuthorOverflow(els.live);
});
