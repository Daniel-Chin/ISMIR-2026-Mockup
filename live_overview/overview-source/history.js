'use strict';
// The history page: every event that has ended, newest first. Data comes from the live
// overview's backend through public-connection.js; overview-common.js has the shared helpers.

const root = document.getElementById('history-events-root');
const connection = document.getElementById('connection-status');
const copyHistoryPromptButton = document.getElementById('copy-history-prompt');
const historyCopyStatus = document.getElementById('history-copy-status');
const archiveNote = document.getElementById('history-archive-note');
const ONGOING_NOTE = 'The conference is ongoing now. Completed sessions are archived here.';
let latestState = null;
const expandedHistoryPaperEventIds = new Set();

/**
 * Before the conference's first event starts, a countdown to it; from then on, that the conference is
 * ongoing. Events before its first day (the Pre-Conference) don't count.
 */
function renderArchiveNote() {
  if (!archiveNote || !latestState) return;
  const conference = latestState.conference || {};
  const day = new Intl.DateTimeFormat('en-CA', { timeZone: conference.timeZone || window.ISMIRSite.timeZone });
  const starts = (latestState.events || []).map(e => Date.parse(e.startsAt))
    .filter(t => Number.isFinite(t) && (!conference.startsOn || day.format(t) >= conference.startsOn));
  const left = starts.length ? Math.min(...starts) - conferenceNow(latestState) : 0;
  if (left <= 0) {
    archiveNote.textContent = ONGOING_NOTE;
    return;
  }
  const s = Math.ceil(left / 1000);
  const days = Math.floor(s / 86400);
  const clock = [Math.floor(s % 86400 / 3600), Math.floor(s % 3600 / 60), s % 60].map(n => String(n).padStart(2, '0')).join(':');
  archiveNote.textContent = `The conference starts in ${days ? `${days}d ` : ''}${clock}. Completed sessions will be archived here.`;
}
setInterval(renderArchiveNote, 1000);

function fmtTime(iso) { return iso ? new Intl.DateTimeFormat('en', { weekday: 'short', hour: '2-digit', minute: '2-digit', timeZone: displayTimeZone() }).format(new Date(iso)) : '—'; }
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
  const state = stateAtConferenceTime(rawState);
  latestState = state;
  renderArchiveNote();
  window.ISMIRTimeZone?.setReferenceDate?.(conferenceNow(state));
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
  const display = stateAtConferenceTime(state || latestState || { events: [] });
  const history = (display.events || [])
    .filter((e) => e.status === 'history')
    .sort((a, b) => new Date(b.endsAt) - new Date(a.endsAt))
    .slice(0, 40)
    .map(compactHistoryEventForPrompt);
  const snapshot = {
    conference: display.conference || {},
    generatedAt: new Date(serverNow()).toISOString(),
    serverNow: display.serverNow || display.updatedAt || null,
    completedEventCount: history.length,
    completedEvents: history,
  };
  return window.ISMIRPrompts.build('history', snapshot);
}


window.addEventListener('ismir-timezone-change', () => { if (latestState) render(latestState); });
window.ISMIRPublic.start({
  ...window.ISMIR_PUBLIC_CONFIG,
  onStatus: (online, label) => setConnectionStatus(connection, online, label),
  onState: state => render(window.ISMIRSite?.localizeState(state) || state),
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
if (copyHistoryPromptButton) copyHistoryPromptButton.addEventListener('click', () => copyPrompt(copyHistoryPromptButton, historyCopyStatus, () => buildHistoryPrompt(latestState)));
