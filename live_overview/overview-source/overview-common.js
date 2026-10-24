'use strict';
/* Helpers shared by the live page (app.js) and the history page (history.js). Classic script,
   loaded before either; its top-level names are visible to both. */

/** The time zone times are shown in: the visitor's pick (timezone-preference.js), else the browser's. */
function displayTimeZone() {
  return window.ISMIRTimeZone?.getTimeZone?.() || (() => {
    try { return Intl.DateTimeFormat().resolvedOptions().timeZone || window.ISMIRSite.timeZone; }
    catch (_) { return window.ISMIRSite.timeZone; }
  })();
}

/** The organisers' test clock (admin.html) applies on live-debug.html only (features.js). */
function testClockApplies(state) {
  return window.ISMIRChannel === 'debug' && Boolean(state?.debugClock?.enabled);
}

/** The server's time now (site-integration.js ISMIRClock), never this computer's own clock. */
function serverNow() {
  return window.ISMIRClock ? window.ISMIRClock.now() : Date.now();
}

/**
 * "Now" for the conference: on live-debug.html, the backend's test clock when an organiser has
 * set one; otherwise, and always on live.html and history.html, the server's real time. Both run
 * on the server's clock, so every computer shows the same moment however its own clock is set.
 */
function conferenceNow(state) {
  const clock = state?.debugClock || {};
  if (testClockApplies(state)) {
    const baseFake = Date.parse(clock.baseFakeIso || '');
    const baseReal = Date.parse(clock.baseRealIso || '');
    const speed = Number.isFinite(Number(clock.speed)) ? Number(clock.speed) : 1;
    if (Number.isFinite(baseFake) && Number.isFinite(baseReal)) {
      return baseFake + (serverNow() - baseReal) * Math.max(0, Math.min(100, speed));
    }
  }
  if (window.ISMIRClock?.synced) return serverNow();
  // Not heard from the server yet (saved schedule): the time it was saved at, else this computer's.
  const t = Date.parse(state?.serverNow || '');
  return Number.isFinite(t) ? t : Date.now();
}

/** Changes whenever the test clock is set, reset or re-timed: then every status must be redone. */
function clockSignature(state) {
  if (window.ISMIRChannel !== 'debug') return '';   // the test clock never reaches live.html
  const clock = state?.debugClock || {};
  return JSON.stringify([Number(clock.revision || 0), Boolean(clock.enabled), clock.baseFakeIso || '', clock.baseRealIso || '', clock.speed ?? 1]);
}

function eventStatusAt(event, now) {
  const start = Date.parse(event?.startsAt || 0);
  const end = Date.parse(event?.endsAt || 0);
  if (!Number.isFinite(start) || !Number.isFinite(end)) return event?.status || 'upcoming';
  if (now < start) return 'upcoming';
  if (now < end) return 'live';
  return 'history';
}

/** The state as of conference time: each event (and its papers) live, upcoming or history. */
function stateAtConferenceTime(state) {
  if (!state) return state;
  const now = conferenceNow(state);
  const events = (state.events || [])
    .filter(e => !e?.debugOnly || window.ISMIRChannel === 'debug')   // organisers' test events: live-debug.html only
    .map(e => {
      const status = eventStatusAt(e, now);
      if (status === e.status && !(e.papers || []).some(p => p?.status !== status)) return e;
      return { ...e, status, papers: (e.papers || []).map(p => ({ ...p, status })) };
    });
  return { ...state, events };
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"]/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[ch]));
}

/** A paper's miniconf page (keyed by its papers.csv uid, not by our display ids). */
function detailUrlFromPaper(p) {
  if (p?.detailUrl) return p.detailUrl;
  if (p?.links?.info) return p.links.info;
  const uid = String(p?.sourcePaperId || '').trim() || (String(p?.id || '').match(/(?:^|-)paper-(\d+)$/) || [])[1] || '';
  return uid ? `${window.ISMIRSite.programSite}/poster_${encodeURIComponent(uid)}.html` : '';
}

function eventInfoUrl(e) {
  const links = e?.links || {};
  return e?.detailUrl || links.info || links.detail || '';
}

/** Tutorials running at the same time are shown together, as one "Tutorials" card. */
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

function setConnectionStatus(node, online, label) {
  if (!node) return;
  node.textContent = label || (online ? 'Realtime connected' : 'Offline');
  node.className = `connection ${online ? 'online' : 'offline'}`;
}

/** Copy text, falling back to a hidden textarea where the Clipboard API is unavailable. */
async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return; } catch (_) { /* fall back */ }
  const ta = document.createElement('textarea');
  ta.value = text;
  ta.setAttribute('readonly', '');
  ta.style.position = 'fixed';
  ta.style.left = '-9999px';
  document.body.appendChild(ta);
  ta.select();
  document.execCommand('copy');
  document.body.removeChild(ta);
}

/** "Copy prompt" buttons: build the prompt (llm-prompts.json, prompt-config.js), copy it, report. */
async function copyPrompt(button, status, build) {
  if (button) button.disabled = true;
  if (status) status.textContent = 'Loading prompt…';
  let prompt;
  try { prompt = await build(); }
  catch (_) {
    if (status) status.textContent = 'Could not load llm-prompts.json. Check the file and try again.';
    return;
  } finally { if (button) button.disabled = false; }
  await copyText(prompt);
  if (status) status.textContent = 'Copied';
  window.setTimeout(() => { if (status) status.textContent = ''; }, 1800);
}
