import { Room } from './room.js';
import { BoardView, timeAgo } from './board.js';
import { WallRooms, WallView, buildWallLayout, sameLayout, screenAspect, wallSlotFor } from './wall.js';
import { SearchBox } from './search.js';
import { apiFetch, apiUrl, takeTokenFromHash, clearToken, onSessionChange, hasSession, serverClock } from './api.js';

const COLORS = { sun: '#ffe27a', mint: '#a8f0c6', sky: '#a9dcff', rose: '#ffbfd0', lilac: '#dccbff', sand: '#f3dcae' };
const USER_KEY = 'pcUser';
const COLS_KEY = 'pcPapersPerRow';
const LBD_COLS_KEY = 'pcLbdsPerRow';
const COLOR_KEY = 'pcLastColor';
const VIEW_KEY = 'pcPaperView';   // 'wall' (default) or 'hall'
const LBD_VIEW_KEY = 'pcLbdView';  // the same for the LBDs

const $ = sel => document.querySelector(sel);
const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { v === undefined ? localStorage.removeItem(k) : localStorage.setItem(k, JSON.stringify(v)); } catch { /* blocked */ } },
};

// ---------- toasts ----------
function toast(message, { error = false, action, ms = 4200 } = {}) {
  const t = el('div', 'pc-toast' + (error ? ' error' : ''));
  t.append(el('span', '', message));
  if (action) {
    const b = el('button', 'pc-btn pc-btn-sm pc-btn-primary', action.label);
    b.type = 'button';
    b.addEventListener('click', () => { action.run(); t.remove(); });
    t.append(b);
  }
  $('#toasts').append(t);
  setTimeout(() => t.remove(), ms);
}

// ---------- composer dialog ----------
const composer = {
  dialog: $('#composer'),
  open({ heading, where = '', text = '', color, max = 600, colors = true, submit = 'Stick it' }) {
    const d = this.dialog, area = $('#composer-text'), counter = $('#composer-counter');
    $('#composer-title').textContent = heading;
    $('#composer-where').textContent = where;
    $('#composer-submit').textContent = submit;
    area.value = text;
    area.maxLength = max;
    let chosen = color || store.get(COLOR_KEY, 'sun');
    const swatches = $('#composer-swatches');
    swatches.hidden = !colors;
    swatches.replaceChildren(...Object.entries(COLORS).map(([name, hex]) => {
      const b = el('button', 'pc-swatch');
      b.type = 'button'; b.style.setProperty('--sw', hex); b.title = name; b.setAttribute('aria-label', name);
      b.setAttribute('aria-pressed', String(name === chosen));
      b.addEventListener('click', () => {
        chosen = name; area.dataset.color = name;
        swatches.querySelectorAll('.pc-swatch').forEach(s => s.setAttribute('aria-pressed', String(s === b)));
      });
      return b;
    }));
    area.dataset.color = colors ? chosen : 'sun';
    const count = () => {
      const n = [...area.value].length;
      counter.textContent = `${n} / ${max}`;
      counter.classList.toggle('over', n > max);
    };
    area.oninput = count;
    count();
    return new Promise(resolve => {
      const done = value => {
        d.close();
        d.onclose = null;
        resolve(value);
      };
      d.querySelector('form').onsubmit = e => {
        e.preventDefault();
        const value = area.value.trim();
        if (!value) return;
        if (colors) store.set(COLOR_KEY, chosen);
        done({ text: value, color: chosen });
      };
      area.onkeydown = e => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) d.querySelector('form').requestSubmit(); };
      $('#composer-cancel').onclick = () => done(null);
      d.onclose = () => resolve(null);
      d.showModal();
      area.focus();
      area.setSelectionRange(area.value.length, area.value.length);
    });
  },
};

// ---------- auth ----------
const app = {
  user: store.get(USER_KEY, null),
  composer,
  toast,
  // Sign-in pages live on the Worker; `return` brings the visitor back to this exact page.
  loginUrl() { return apiUrl('/auth/slack/start?return=' + encodeURIComponent(location.href)); },
  slackApp: null,   // {team, app} from /api/me when the Slack-app sign-in is set up
  login() {
    // Phones and tablets: if the Slack app is installed, Slack's web sign-in jumps into it after
    // the email code and never comes back. So go to the app on purpose: our Home tab there shows
    // "Enter the Discussion", a one-tap sign-in link. Never redirect again on our own afterwards:
    // iOS may still be showing its "Open in Slack?" prompt, and a second (web) sign-in would
    // pull the user away from our Home tab into Slackbot. If the app really isn't there, offer
    // the browser sign-in as a tap instead.
    if (this.slackApp && matchMedia('(pointer: coarse)').matches) {
      const { team, app: id } = this.slackApp;
      let left = false;
      const onHide = () => { if (document.hidden) left = true; };
      document.addEventListener('visibilitychange', onHide);
      setTimeout(() => {
        document.removeEventListener('visibilitychange', onHide);
        if (left || document.hidden) return;
        // Inside Slack's in-app browser the slack:// link does nothing. Never send phones to the
        // web sign-in here: with the Slack app installed it ends in Slackbot. Point to the Home
        // tab instead; devices without Slack can still use the browser sign-in.
        toast(`Open the ${hall.program?.conference?.slackAppName || 'our'} app in Slack and tap “Enter the Discussion”.`, {
          action: { label: 'Open Slack', run: () => { location.href = `https://slack.com/app_redirect?team=${encodeURIComponent(team)}&app=${encodeURIComponent(id)}`; } },
          ms: 20000,
        });
        toast('No Slack app on this device?', { action: { label: 'Sign in in the browser', run: () => { location.href = this.loginUrl(); } }, ms: 20000 });
      }, 3000);
      location.href = `slack://app?team=${encodeURIComponent(team)}&id=${encodeURIComponent(id)}&tab=home`;
      return;
    }
    location.href = this.loginUrl();
  },
  /**
   * Before a new note (board.js, wall.js). Once the Opening Session has started, a note on a paper
   * or LBD board first shows a notice pointing to Slack; closing it carries on to the note. The
   * Welcome Reception never shows it. Resolves false only if the note should not be written.
   */
  beforeNote(board) {
    if (board === 'welcome' || !conferenceOpen()) return Promise.resolve(true);
    const d = $('#slack-notice'), link = $('#slack-notice-link');
    const [kind, uid] = String(board).split(':');
    const item = kind === 'lbd' ? hall.lbdById?.[uid] : hall.program?.papers[uid];
    const channel = /^https:\/\//.test(item?.channelUrl || '') ? item.channelUrl : '';
    link.hidden = !channel;
    if (channel) link.href = channel;
    return new Promise(resolve => {
      d.onclose = () => { d.onclose = null; resolve(true); };   // Close, Esc or Open Slack: the note still opens
      d.showModal();
      $('#slack-notice-close').focus();
    });
  },
  /** Returns true when signed in; otherwise nudges toward Slack sign-in. */
  requireLogin(what) {
    if (this.user) return true;
    toast(`Sign in with Slack to ${what}.`, { action: { label: 'Sign in', run: () => this.login() }, ms: 7000 });
    return false;
  },
};

function initials(name) {
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map(s => [...s][0].toUpperCase()).join('') || '?';
}

function renderAuth() {
  // Notes look draggable only to people who may move them (styles.css).
  document.documentElement.classList.toggle('pc-signed-in', !!app.user);
  const slot = $('#auth-slot');
  if (!app.user) {
    const b = el('a', 'theme-toggle pc-signin', 'Sign in');
    b.title = 'Sign in with Slack';
    b.href = app.loginUrl();
    b.addEventListener('click', e => { e.preventDefault(); app.login(); });
    slot.replaceChildren(b);
    return;
  }
  const chip = el('span', 'pc-user-chip');
  chip.append(el('span', 'pc-avatar', initials(app.user.name)));
  // Your Slack name, cut to a fixed width so it never pushes into the nav; hover shows it all.
  const name = el('span', 'pc-name', app.user.name);
  chip.tabIndex = 0;                    // keyboard users can reach the full-name tooltip too
  chip.dataset.full = app.user.name;   // read by the CSS tooltip
  chip.append(name);
  const out = el('button', 'pc-signout', 'Sign out');
  out.type = 'button';
  out.addEventListener('click', async () => {
    clearToken();
    await fetch(apiUrl('/auth/logout'), { method: 'POST' }).catch(() => {});
    store.set(USER_KEY, undefined);
    location.reload();
  });
  slot.replaceChildren(chip, out);
}

/**
 * Every live connection's hello says who the server thinks we are. If /api/me hasn't answered
 * yet (it races the connections at start-up), take that answer: a signed-in visitor never sees
 * "Sign in" because the check is still on its way.
 */
function userFromRoom(room) {
  if (!room.me || app.user?.id === room.me.id) return;
  if (app.user) return;   // /api/me already answered with someone: it stays authoritative
  if (!hasSession()) return;   // signed out (here or on the Live Overview)
  app.user = { ...room.me };
  renderAuth();
  window.dispatchEvent(new Event('pc-egg-ready'));   // the easter egg may be waiting to claim a find
}

async function refreshUser() {
  try {
    const sent = Date.now();
    const res = await apiFetch('/api/me', { cache: 'no-store' });
    const received = Date.now();
    const data = await res.json();
    serverClock.sync(Number(data.now), sent, received);
    app.user = data.user;
    app.slackApp = data.slackApp || null;
    if (!data.user) clearToken();   // expired or revoked
    store.set(USER_KEY, data.user || undefined);
  } catch { /* offline: keep the cached name for display only; the server decides on writes */ }
  renderAuth();
}

// ---------- time helpers ----------
function zonedToDate(date, hhmm, timeZone) {
  // Interpret date+time as wall-clock in `timeZone` and return the real instant.
  const [h, m] = hhmm.split(':').map(Number);
  const guess = new Date(`${date}T${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}:00Z`);
  const parts = Object.fromEntries(new Intl.DateTimeFormat('en-US', { timeZone, hourCycle: 'h23', year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
    .formatToParts(guess).map(p => [p.type, p.value]));
  const asIfUtc = Date.UTC(+parts.year, +parts.month - 1, +parts.day, +parts.hour, +parts.minute);
  return new Date(guess.getTime() - (asIfUtc - guess.getTime()));
}

/** Has the Opening Session (program.conference.opening, in the conference time zone) started? */
function conferenceOpen(now = serverClock.now()) {
  const opening = hall.program?.conference?.opening;
  if (!opening?.date || !opening?.start) return false;
  return now >= zonedToDate(opening.date, opening.start, hall.program.conference.timezone).getTime();
}

const viewerZone = () => window.ISMIRTimeZone?.getTimeZone?.() || Intl.DateTimeFormat().resolvedOptions().timeZone;

const SLOT_LABELS = { oral: 'Oral', poster: 'Poster', session: '', lbd: '' };

/** One slot in the zone chosen in the hero, plus the venue time when they differ. */
function slotTimes(slot) {
  const venue = hall.program.conference.timezone;
  const venueDay = slot.date ? new Date(slot.date + 'T12:00:00Z').toLocaleDateString('en-US', { weekday: 'short', timeZone: 'UTC' }) : '';
  const venueText = `${venueDay} ${slot.start}–${slot.end}`.trim();
  if (!slot.date || !slot.start) return { main: venueText, venue: '' };
  const zone = viewerZone();
  const start = zonedToDate(slot.date, slot.start, venue), end = zonedToDate(slot.date, slot.end, venue);
  const day = new Intl.DateTimeFormat('en-US', { timeZone: zone, weekday: 'short' }).format(start);
  const hm = d => new Intl.DateTimeFormat('en-GB', { timeZone: zone, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' }).format(d);
  const offset = window.ISMIRTimeZone?.getUTCOffset?.(start) || '';
  const main = `${day} ${hm(start)}–${hm(end)}${offset ? ' ' + offset : ''}`;
  const city = hall.program.conference.venueCity || 'Venue';
  return { main, venue: zone === venue ? '' : `${city} ${venueText}` };
}

/** A poster session, or "LBD": the one session every LBD shares. */
const sessionById = id => (id === 'LBD' ? hall.program.lbdSession : hall.program.sessions[id]);

function refreshSessionTimes() {
  if (!hall.program) return;
  document.querySelectorAll('[data-session-time]').forEach(node => {
    const slots = sessionById(node.dataset.sessionTime)?.slots || [];
    node.querySelectorAll('[data-slot]').forEach(line => {
      const t = slotTimes(slots[Number(line.dataset.slot)]);
      line.querySelector('.pc-time-main').textContent = t.main;
      const venue = line.querySelector('.pc-time-venue');
      venue.textContent = t.venue;
      venue.hidden = !t.venue;
    });
  });
}

/** "Oral · Mon 10:00–10:30 UTC+4" and "Poster · Mon 10:30–11:30 UTC+4", one per line. */
function timeBlock(session, cls) {
  const box = el('span', cls);
  box.dataset.sessionTime = session.id;
  session.slots.forEach((slot, i) => {
    const line = el('span', 'pc-time-line');
    line.dataset.slot = i;
    const label = SLOT_LABELS[slot.kind];
    if (label) line.append(el('b', 'pc-time-kind', label), el('span', 'pc-time-sep', '·'));
    line.append(el('span', 'pc-time-main'), el('span', 'pc-time-venue'));
    box.append(line);
  });
  return box;
}

function prettyDate(iso) {
  if (!iso) return '';
  return new Date(iso + 'T12:00:00Z').toLocaleDateString(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' });
}

// ---------- paper hall ----------
const hall = { program: null, counts: {}, open: null };

function sessionNoteCount(session) {
  return session.papers.reduce((sum, uid) => sum + (hall.counts['paper:' + uid] || 0), 0);
}

function renderHall() {
  const { program } = hall;
  const root = $('#paper-hall');
  root.replaceChildren(...program.days.map(day => {
    const row = el('div', 'pc-day-row');
    row.dataset.day = day.day;
    const label = el('h3', 'pc-day-label');
    label.append(el('strong', '', day.day), el('span', '', `${prettyDate(day.date)} · ${day.sessions.length} session${day.sessions.length > 1 ? 's' : ''}`));
    const grid = el('div', 'pc-session-grid');
    for (const id of day.sessions) grid.append(sessionCard(program.sessions[id]));
    const slot = el('div', 'pc-session-slot');
    row.append(label, grid, slot);
    return row;
  }));
}

function sessionCard(s) {
  const card = el('button', 'pc-session-card');
  card.type = 'button';
  card.dataset.session = s.id;
  card.setAttribute('aria-expanded', String(hall.open?.id === s.id));
  card.append(el('span', 'pc-session-id', s.id));
  card.append(timeBlock(s, 'pc-session-time'));
  const stats = el('span', 'pc-session-stats');
  stats.append(el('span', 'pc-stat', `${s.papers.length} papers`), el('span', 'pc-stat-sep', '·'));
  const notes = el('span', 'pc-stat pc-note-count', `${sessionNoteCount(s)} notes`);
  notes.dataset.sessionCount = s.id;
  stats.append(notes);
  card.append(stats);
  card.addEventListener('click', () => (hall.open?.id === s.id ? closeSession() : openSession(s.id, true)));
  return card;
}

// ---------- live session rooms, shared by the wall and the hall ----------
// One connection per session for the whole page: the wall and an opened hall session use the
// same Room, so switching views or opening a session shows its notes at once. Once every
// session is live, the hall's note counts come from these rooms instead of /api/counts.
const sessionRooms = new Map();
// All sessions' notes from one request (see roomSnapshot in the Worker): rooms show them at
// once while their live connections, which browsers open one at a time, catch up.
const snapshot = { at: 0, rooms: {} };
const SNAPSHOT_FRESH_MS = 15_000;
function sessionRoom(sid) {
  let room = sessionRooms.get(sid);
  if (!room) {
    room = new Room(sid === 'LBD' ? 'lbd' : 'session:' + sid);
    room.subscribe(ev => {
      if (ev.type === 'reset') userFromRoom(room);
      if (['reset', 'upsert', 'remove'].includes(ev.type)) scheduleBadges();
    });
    sessionRooms.set(sid, room);
    if (Date.now() - snapshot.at < SNAPSHOT_FRESH_MS) room.seed(snapshot.rooms[sid]);
  }
  return room;
}

async function loadSnapshot() {
  try {
    const ids = Object.keys(hall.program.sessions);
    if (hall.program.lbds?.length) ids.push('LBD');
    const res = await apiFetch('/api/snapshot?rooms=' + encodeURIComponent(ids.join(',')), { cache: 'no-store' });
    if (!res.ok) return;
    const data = await res.json();
    snapshot.at = Date.now();
    snapshot.rooms = data.rooms || {};
    for (const [sid, room] of sessionRooms) room.seed(snapshot.rooms[sid]);
  } catch { /* the live connections bring the notes anyway */ }
}
const allSessionsLive = () => !!hall.program && Object.keys(hall.program.sessions).every(sid => sessionRooms.get(sid)?.ready);

let badgeFrame = 0;
function scheduleBadges() {
  badgeFrame ||= requestAnimationFrame(() => {
    badgeFrame = 0;
    if (!hall.program) return;
    for (const [sid, room] of sessionRooms) {
      if (!room.ready) continue;
      for (const uid of hall.program.sessions[sid]?.papers || []) hall.counts['paper:' + uid] = room.countFor('paper:' + uid);
      const badge = document.querySelector(`[data-session-count="${CSS.escape(sid)}"]`);
      if (badge) badge.textContent = `${sessionNoteCount(hall.program.sessions[sid])} notes`;
    }
  });
}

// ---------- paper wall and LBD wall (alternative views of the halls) ----------
// What each wall shows (see wall.js): the papers by poster session, two rows to an area; the
// LBDs in one area (one per group, should LBDs get a group), as many rows as fit the screen.
const paperWallSpec = program => ({
  prefix: 'paper', rows: 2,
  groups: program.days.flatMap(day => day.sessions.map(sid => ({ id: sid, day: day.day, uids: program.sessions[sid]?.papers || [] }))),
});
const lbdWallSpec = program => ({
  prefix: 'lbd', rows: 'fit',
  groups: program.lbdGroups?.length
    ? program.lbdGroups.map(g => ({ id: 'LBD-' + g.id, group: g.id, theme: g.theme, uids: g.lbds }))
    : [{ id: 'LBD', group: '', uids: program.lbds.map(l => l.uid) }],
});

// match: the uids a search shows (null: no search). See initSearch.
const papers = { view: 'hall', wall: null, layout: null, match: null, search: null, results: null };
const lbds = { view: 'wall', wall: null, layout: null, match: null, search: null };
const wallLayout = () => (papers.layout ||= buildWallLayout(paperWallSpec(hall.program), screenAspect()));
const lbdWallLayout = () => (lbds.layout ||= buildWallLayout(lbdWallSpec(hall.program), screenAspect()));

function makeWall(rooms) {
  papers.wall = new WallView($('#paper-wall'), {
    room: rooms, app, items: hall.program.papers, layout: wallLayout(), buildPin: pinCard,
    regionHead: wallRegionHead, noteTag: paperTag, onFullscreen: dockSearch(papers, '#paper-search'),
  });
  papers.wall.setFilter(papers.match, { fit: !!papers.match });
  refreshSessionTimes();
}

function makeLbdWall(rooms) {
  lbds.wall = new WallView($('#lbd-wall'), {
    room: rooms, app, title: 'LBD Wall', items: hall.lbdById, layout: lbdWallLayout(), buildPin: p => pinCard(p, { lbd: true }),
    regionHead: lbdRegionHead, noteTag: lbdTag, onFullscreen: dockSearch(lbds, '#lbd-search'),
  });
  lbds.wall.setFilter(lbds.match, { fit: !!lbds.match });
  refreshSessionTimes();
}

/**
 * Expanded, a wall takes its section's search box along, in a bar under its title. A button
 * left of the zoom buttons hides the bar for more wall (remembered in this browser); the search
 * itself stays on.
 */
const FS_SEARCH_KEY = 'pcFsSearchHidden';
const dockSearch = (state, home) => on => {
  const root = state.search?.root;
  if (!root) return;
  const wall = state.wall;
  if (on) {
    const bar = el('div', 'pc-fs-search');
    bar.append(root);
    wall.titleBar.after(bar);
    const toggle = el('button', 'pc-btn pc-btn-sm pc-zoom-btn pc-fs-search-toggle');
    toggle.type = 'button';
    const show = hidden => {
      bar.hidden = hidden;
      toggle.textContent = hidden ? 'Search' : 'Hide search';
      toggle.title = hidden ? 'Show the search box' : 'Hide the search box';
      toggle.setAttribute('aria-pressed', String(!hidden));
    };
    toggle.addEventListener('click', () => {
      const hidden = !bar.hidden;
      store.set(FS_SEARCH_KEY, hidden);
      // The wall gets (or gives back) the bar's height: keep looking at the same place.
      const view = wall.camera();
      show(hidden);
      wall.layout(true);
      wall.setCamera(wall.reachable(view));
      if (!hidden) state.search.input.focus();
    });
    show(!!store.get(FS_SEARCH_KEY, false));
    wall.tools.prepend(toggle);
  } else {
    $(home).prepend(root);
    wall.frame.querySelector('.pc-fs-search')?.remove();
    wall.tools.querySelector('.pc-fs-search-toggle')?.remove();
  }
};

// Rotating a tablet or resizing the window can call for another arrangement of a wall (more
// or fewer areas per row): rebuild the view, keeping its live connections.
function relayoutWall(state, spec, make) {
  const next = buildWallLayout(spec, screenAspect());
  if (sameLayout(next, state.layout)) return;
  state.layout = next;
  if (!state.wall) return;
  const expanded = state.wall.frame.classList.contains('is-fullscreen');
  const rooms = state.wall.room;
  state.wall.destroy({ keepRooms: true });
  make(rooms);
  if (expanded) state.wall.toggleFullscreen();
}
// Only a change of width (rotating a tablet, resizing a window) can call for another arrangement.
// On phones and tablets the address bar shows and hides as the page scrolls, changing only the
// height: rebuilding the walls then made them jump while scrolling.
let wallResizeTimer = 0, wallResizeWidth = window.innerWidth;
window.addEventListener('resize', () => {
  if (window.innerWidth === wallResizeWidth) return;
  wallResizeWidth = window.innerWidth;
  clearTimeout(wallResizeTimer);
  wallResizeTimer = setTimeout(() => {
    if (!hall.program) return;
    relayoutWall(papers, paperWallSpec(hall.program), makeWall);
    if (hall.program.lbds?.length) relayoutWall(lbds, lbdWallSpec(hall.program), makeLbdWall);
  }, 300);
});
/** "P1-01" for a note on a paper's board: shown after the author on every paper note. */
const paperTag = n => (n.board?.startsWith('paper:') ? hall.program.papers[n.board.slice(6)]?.displayId || '#' + n.board.slice(6) : '');

/** Switch the Paper Hall section between the hall (session cards) and the wall. */
function setPaperView(view, { link = true } = {}) {
  view = view === 'wall' ? 'wall' : 'hall';
  // Leaving an expanded wall: collapse it first, while it is still visible to measure.
  if (view === 'hall' && papers.wall?.frame.classList.contains('is-fullscreen')) papers.wall.toggleFullscreen();
  papers.view = view;
  store.set(VIEW_KEY, view);
  $('#paper-hall').hidden = view !== 'hall';
  $('#paper-wall').hidden = view !== 'wall';
  $('#paper-view-title').textContent = view === 'wall' ? 'Paper Wall' : 'Paper Hall';
  document.querySelectorAll('#paper-view button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.view === view)));
  if (view === 'wall') {
    closeSession({ keepHash: true });
    if (papers.wall) papers.wall.shown();
    else {
      // One live connection per session. Kept (idle) while the hall is shown, so going back to
      // the wall, or jumping to a paper on it, shows every note at once.
      const rooms = new WallRooms(new Map(Object.keys(hall.program.sessions).map(sid => [sid, sessionRoom(sid)])),
        msg => hall.program.papers[msg.board.slice('paper:'.length)]?.session);
      rooms.subscribe(ev => { if (ev.type === 'error') handleRoomError(ev); });
      makeWall(rooms);
    }
  }
  if (link) setLink(view === 'wall' ? '#wall' : '#papers');
}

function initPaperView() {
  $('#paper-view').addEventListener('click', e => {
    const b = e.target.closest('button[data-view]');
    if (b) setPaperView(b.dataset.view);
  });
  const shared = new URLSearchParams(location.hash.slice(1));
  setPaperView(shared.has('wall') ? 'wall' : shared.has('hall') ? 'hall' : store.get(VIEW_KEY, 'wall'), { link: false });
}

/** An area's title band on a wall: "Mon · PS-01" and its Oral / Poster times. */
function wallRegionHead(region, s = hall.program.sessions[region.id], name = `${region.day} · ${s.id}`) {
  // A div, not a <button>: overview.css restyles every bare button.
  const head = el('div', '');
  head.setAttribute('role', 'button');
  head.tabIndex = 0;
  head.append(el('span', 'pc-wall-region-name', name), timeBlock(s, 'pc-wall-region-time'));
  return head;
}

/** The LBD area's band: "Thu · Late-Breaking Demos" (or its group) and the LBD session's time. */
function lbdRegionHead(region) {
  const s = hall.program.lbdSession, date = s.slots[0]?.date;
  const day = date ? new Date(date + 'T12:00:00Z').toLocaleDateString('en-US', { weekday: 'short', timeZone: 'UTC' }) + ' · ' : '';
  if (!region.theme) return wallRegionHead(region, s, day + 'Late-Breaking Demos');
  // A group: its theme only. Every group has the same time, shown once above the hall.
  const head = el('div', 'pc-wall-region-themed');
  head.setAttribute('role', 'button');
  head.tabIndex = 0;
  head.append(el('span', 'pc-wall-region-name', region.theme));
  return head;
}

/** A link to a paper (or LBD) the search hides: show everything again first. */
function unhide(state, uid) {
  if (state.match && !state.match.has(String(uid))) state.search.clear();
}

/** Hall -> Wall: show paper `uid` on the wall, at 1000%, in the middle of the view. */
function showOnWall(uid) {
  unhide(papers, uid);
  setPaperView('wall', { link: false });
  setLink('#wall&paper=' + encodeURIComponent(uid));
  document.getElementById('papers')?.scrollIntoView();
  papers.wall.focusPaper(uid);
}

/** Wall -> Hall: open the paper's session and bring its card into view. */
function showInHall(uid) {
  setPaperView('hall', { link: false });
  openPaper(uid);
}

/** The same two jumps for an LBD. */
function showLbdOnWall(uid) {
  setLbdView('wall', { link: false });
  setLink('#lbdwall&lbd=' + encodeURIComponent(uid));
  openLbd(uid);
}
function showLbdInHall(uid) {
  setLbdView('hall', { link: false });
  setLink('#lbdhall&lbd=' + encodeURIComponent(uid));
  openLbd(uid);
}

/** "Presented In-person" plus a link to the same paper in the other view. */
function presenterRow(p, cls, jump) {
  const row = el('div', cls);
  row.append(el('div', 'presenter-mode-line', PRESENTER_LABELS[p.presenterMode] || 'Presentation mode TBA'));
  if (!jump) return row;
  const a = el('a', 'pc-view-jump', jump.label);
  a.href = '#';
  a.title = jump.title;
  a.addEventListener('click', e => { e.preventDefault(); jump.go(p.uid); });
  row.append(a);
  return row;
}

/** A paper (or, lbd: true, an LBD) pinned to the wall: title, links, a Comment button; authors and time at the foot. */
function pinCard(p, { lbd = false } = {}) {
  const card = el('article', '');
  card.append(el('span', 'pc-pin-tack'));
  const top = el('div', 'pc-pin-top');
  const comment = el('a', 'link-button pc-add-note pc-pin-comment', '+ Comment');
  comment.href = '#'; comment.setAttribute('role', 'button'); comment.dataset.comment = '';
  top.append(paperIdLink(p, 'pc-pin-id pc-permalink', lbd ? 'lbdwall' : 'wall'), comment);
  const title = el('h4', 'pc-pin-title');
  const titleLink = linkButton(lbd ? p.pageUrl && p.pageUrl + '#detail' : p.posterUrl, p.title);
  if (titleLink) { titleLink.className = ''; title.append(titleLink); } else title.textContent = p.title;
  title.title = p.title;
  const foot = el('div', 'pc-pin-foot');
  const authors = el('span', 'pc-pin-authors', p.authors);
  authors.title = p.authors;
  foot.append(authors, presentTime(p));
  const mode = presenterRow(p, 'pc-pin-mode', lbd
    ? { label: 'In the Hall →', title: 'Open this LBD in the Hall view', go: showLbdInHall }
    : { label: 'In the Hall →', title: 'Open this paper in the Hall view', go: showInHall });
  card.append(top, title, mode, paperLinks(p), foot);
  return card;
}

/** When the paper is presented: its session's poster slot (LBDs: the LBD session), in the zone chosen in the hero. */
function presentTime(p) {
  const s = p.session ? hall.program.sessions[p.session] : hall.program.lbdSession;
  const box = el('span', 'pc-pin-time');
  if (!s) return box;
  const i = Math.max(0, s.slots.findIndex(slot => slot.kind === 'poster'));
  box.dataset.sessionTime = s.id;
  const line = el('span', 'pc-time-line');
  line.dataset.slot = i;
  line.append(el('span', 'pc-time-main'), el('span', 'pc-time-venue'));
  box.append(line);
  return box;
}

function closeSession({ keepHash = false } = {}) {
  if (!hall.open) return;
  for (const b of hall.open.boards) b.destroy();
  hall.open.unsubscribe();   // the room itself stays: it is shared (sessionRoom)
  hall.open.panel.remove();
  document.querySelectorAll('.pc-session-card[aria-expanded="true"]').forEach(c => c.setAttribute('aria-expanded', 'false'));
  hall.open = null;
  if (!keepHash && location.hash.startsWith('#session=')) setLink('#papers');
}

/**
 * Shareable addresses (the URL always shows where you are, so it can be copied as is):
 *   lounge.html#welcome                    Welcome Reception
 *   lounge.html#papers                     Paper Hall
 *   lounge.html#wall                       Paper Hall, as the Paper Wall
 *   lounge.html#wall&paper=3               one paper on the wall    } what "copy link" shares,
 *   lounge.html#hall&paper=3               one paper in the hall    } from the wall / the hall
 *   lounge.html#session=PS-03              a poster session, opened
 *   lounge.html#session=PS-03&paper=3      one paper's board in it (paper = papers.csv uid)
 *   lounge.html#paper=3                    same; the session is looked up (miniconf links use this)
 *   lounge.html#lbd                        LBD Hall section (in the view used last)
 *   lounge.html#lbdwall / #lbdhall         the LBDs, as the LBD Wall / the LBD Hall
 *   lounge.html#lbdwall&lbd=569            one LBD on the wall  } what "copy link" shares;
 *   lounge.html#lbdhall&lbd=569            one LBD in the hall  } 569 = its CMT id (lbd_569.html)
 *   lounge.html#lbd=569                    one LBD, in the view used last
 */
function setLink(hash) {
  if (location.hash !== hash) history.replaceState(null, '', location.pathname + location.search + hash);
}

function paperLink(uid) {
  const p = hall.program.papers[uid];
  return p ? `#session=${encodeURIComponent(p.session)}&paper=${encodeURIComponent(uid)}` : '#papers';
}

/** Go to whatever the current #fragment names. */
function route() {
  const params = new URLSearchParams(location.hash.slice(1));
  const paper = params.get('paper'), session = params.get('session'), lbd = params.get('lbd');
  if (hall.program.lbds?.length && (lbd || params.has('lbdwall') || params.has('lbdhall'))) {
    if (params.has('lbdwall') && lbds.view !== 'wall') setLbdView('wall', { link: false });
    if (params.has('lbdhall') && lbds.view !== 'hall') setLbdView('hall', { link: false });
    if (lbd) openLbd(lbd); else keepInView(document.getElementById('lbd'));
    return;
  }
  // Shared links (#wall&paper=… / #hall&paper=…) open that view, whatever the visitor used last.
  if (params.has('wall') && papers.view !== 'wall') setPaperView('wall', { link: false });
  if (params.has('hall') && papers.view !== 'hall') setPaperView('hall', { link: false });
  if (location.hash === '#wall') {
    document.getElementById('papers')?.scrollIntoView();
    return;
  }
  // On the wall, a paper or session link flies there instead of opening the hall.
  if (papers.view === 'wall' && ((paper && hall.program.papers[paper]) || (session && hall.program.sessions[session]))) {
    document.getElementById('papers')?.scrollIntoView();
    if (paper && hall.program.papers[paper]) { unhide(papers, paper); papers.wall.focusPaper(paper); } else { papers.search?.clear(); papers.wall.focusSession(session); }
    return;
  }
  if (paper && hall.program.papers[paper]) return openPaper(paper);
  if (session && hall.program.sessions[session]) {
    if (hall.open?.id !== session) openSession(session, true);
    return;
  }
  const section = location.hash.slice(1);
  // The wall above the LBD Hall can still be growing, so keep the section in place meanwhile.
  if (['welcome', 'papers', 'lbd', 'home'].includes(section)) keepInView(document.getElementById(section));
}

function openPaper(uid) {
  const paper = hall.program.papers[uid];
  if (!paper) { document.getElementById('papers')?.scrollIntoView(); return; }
  // Found by the search: its card is in the results.
  if (papers.match?.has(String(uid))) {
    const found = document.getElementById('paper-' + uid);
    if (found) { setLink('#hall&paper=' + encodeURIComponent(uid)); focusCard(found); return; }
  }
  if (hall.open?.id !== paper.session) openSession(paper.session, false);
  setLink(paperLink(uid));
  const card = document.getElementById('paper-' + uid);
  if (card) focusCard(card);
}

/** Highlight a card and keep it just under the sticky header while the page settles. */
function focusCard(card) {
  card.classList.add('pc-paper-focus');
  setTimeout(() => card.classList.remove('pc-paper-focus'), 2600);
  keepInView(card);
}

/** Keep `node` just under the sticky header while the page settles. */
function keepInView(node) {
  // Put the top edge just inside the view, right under the sticky header. Content above
  // (boards, fonts) can still shift while the page settles, so re-align a few times, unless
  // the user scrolls.
  const align = () => {
    const header = document.querySelector('.site-header')?.getBoundingClientRect().bottom || 0;
    const y = node.getBoundingClientRect().top + scrollY - header - 8;   // 8px: the focus outline shows
    if (Math.abs(y - scrollY) > 2) window.scrollTo({ top: y, behavior: 'instant' });
  };
  let userScrolled = false;
  const stop = () => { userScrolled = true; };
  for (const ev of ['wheel', 'touchstart', 'keydown', 'pointerdown']) addEventListener(ev, stop, { once: true, passive: true });
  for (const ms of [0, 150, 500, 1200, 2500]) setTimeout(() => { if (!userScrolled) align(); }, ms);
}

function openSession(id, scroll) {
  const s = hall.program.sessions[id];
  if (!s) return;
  papers.search?.clear();   // sessions are hidden while searching
  closeSession({ keepHash: true });
  setLink('#session=' + encodeURIComponent(id));
  const card = document.querySelector(`.pc-session-card[data-session="${CSS.escape(id)}"]`);
  card?.setAttribute('aria-expanded', 'true');
  const slot = card.closest('.pc-day-row').querySelector('.pc-session-slot');

  const room = sessionRoom(id);
  const panel = el('section', 'pc-session-panel');
  panel.setAttribute('aria-label', `Session ${id}`);
  const head = el('div', 'pc-session-panel-head');
  const left = el('div');
  left.append(el('h3', '', `Poster session ${id}`));
  const sub = el('div', 'pc-sub');
  sub.append(timeBlock(s, 'pc-panel-time'));
  left.append(sub);
  const tools = el('div', 'pc-head-actions');
  const segLabel = el('span', 'pc-seg-label', 'Per row');
  const seg = el('div', 'pc-seg');
  seg.setAttribute('role', 'group');
  seg.setAttribute('aria-label', 'Papers per row');
  let cols = store.get(COLS_KEY, 2);
  // The overview's paper-card styles are scoped to #live-events; only one session panel is
  // open at a time, so its grid can borrow that id and render the overview's cards as-is.
  const grid = el('div', 'pc-paper-grid live-poster-paper-panel');
  grid.id = 'live-events';
  const setCols = n => {
    cols = n; store.set(COLS_KEY, n);
    grid.style.setProperty('--cols', n);
    requestAnimationFrame(() => syncAuthorOverflow(grid));
    seg.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(Number(b.dataset.n) === n)));
  };
  for (const n of [1, 2, 3, 4]) {
    const b = el('button', '', String(n));
    b.type = 'button'; b.dataset.n = n;
    b.addEventListener('click', () => {
      setCols(n);
      // New card widths: once the boards have re-laid out, show each one's default view again.
      requestAnimationFrame(() => requestAnimationFrame(() => { for (const board of hall.open?.boards || []) { board.layout(); board.fitToNotes(); } }));
    });
    seg.append(b);
  }
  const collapse = el('button', 'pc-btn pc-btn-sm pc-fs-btn', '▲ Collapse');
  collapse.type = 'button';
  collapse.addEventListener('click', () => { const c = card; closeSession(); c?.scrollIntoView({ block: 'nearest' }); });
  tools.append(segLabel, seg, collapse);
  head.append(left, tools);
  panel.append(head, grid);
  slot.append(panel);
  setCols(cols);
  requestAnimationFrame(() => syncAuthorOverflow(grid));
  refreshSessionTimes();

  const boards = [];
  const counters = new Map();
  for (const uid of s.papers) {
    const p = hall.program.papers[uid];
    const cardEl = paperCard(p);
    grid.append(cardEl);
    const mount = cardEl.querySelector('.pc-paper-board');
    const board = new BoardView(mount, {
      room, board: 'paper:' + uid, title: `#${uid} ${p.title}`, app, fitNotes: true, dblclickExpands: true,
      emptyText: 'No notes yet: tap + Note to start the discussion',
      noteTag: paperTag,
      // The same note also appears on the Paper Wall, beside this paper's pin.
      createExtras: () => wallSlotFor(wallLayout(), String(uid), [...room.notes.values()]),
    });
    boards.push(board);
    cardEl.querySelector('[data-add]').addEventListener('click', e => { e.preventDefault(); board.compose(); });
    counters.set('paper:' + uid, cardEl.querySelector('[data-count]'));
  }
  const updateCounts = () => {
    let total = 0;
    for (const [bid, node] of counters) {
      const n = room.countFor(bid);
      total += n;
      node.textContent = `${n} note${n === 1 ? '' : 's'}`;
      hall.counts[bid] = n;
    }
    const badge = document.querySelector(`[data-session-count="${CSS.escape(id)}"]`);
    if (badge) badge.textContent = `${total} notes`;
  };
  const unsubscribe = room.subscribe(ev => {
    // With the wall open its rooms report errors already; avoid showing each one twice.
    if (ev.type === 'error' && !papers.wall) handleRoomError(ev);
    if (['reset', 'upsert', 'remove'].includes(ev.type)) updateCounts();
  });
  if (room.ready) updateCounts();
  hall.open = { id, room, panel, boards, unsubscribe };
  if (scroll) requestAnimationFrame(() => panel.scrollIntoView({ behavior: 'smooth', block: 'start' }));
}

const PRESENTER_LABELS = { online: 'Presented Virtual', mixed: 'Presented In-person + Virtual', onsite: 'Presented In-person' };

/** Overview-style link button; only https targets are rendered. */
function linkButton(href, label) {
  if (!/^https:\/\//.test(href || '')) return null;
  const a = el('a', 'link-button', label);
  a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer';
  return a;
}

/** The link people share: it opens this paper in `view` ('wall' or 'hall'), or this LBD in
 * 'lbdwall' / 'lbdhall', whatever view the visitor used last. */
const shareLink = (uid, view) => location.origin + location.pathname + location.search +
  (view.startsWith('lbd') ? `#${view}&lbd=${encodeURIComponent(uid)}` : `#${view}&paper=${encodeURIComponent(uid)}`);

/** The paper id as a permalink: click it to copy a link to this paper in the view it sits in. */
function paperIdLink(p, cls, view) {
  const label = p.displayId || '#' + p.uid;
  const id = el('a', cls, label);
  id.href = shareLink(p.uid, view);
  id.title = 'Copy a link to this paper';
  id.addEventListener('click', async e => {
    e.preventDefault();
    try {
      await navigator.clipboard.writeText(shareLink(p.uid, view));
      toast(`Link to ${label} copied. Feel free to share it with your friends!`);
    } catch {
      // No clipboard (old browser, or permission refused): leave the link in the address bar.
      history.replaceState(null, '', shareLink(p.uid, view));
      toast(`Link to ${label} is in the address bar. Feel free to share it with your friends!`);
    }
  });
  return id;
}

/**
 * Same markup and classes as the live overview's paper card, minus its Zoom/speaker parts.
 * LBDs use it too (lbd: true): the LBD Wall, and links to the miniconf LBD page.
 */
function paperCard(p, { lbd = false } = {}) {
  const card = el('article', 'paper-card live-paper-card');
  card.id = (lbd ? 'lbd-' : 'paper-') + p.uid;

  const status = el('div', 'paper-card-status-row');
  const count = el('span', 'pc-note-count', '0 notes');
  count.dataset.count = '';
  const id = paperIdLink(p, 'paper-id pc-permalink', lbd ? 'lbdhall' : 'hall');
  status.append(id, count);

  const copy = el('div', 'paper-card-copy');
  const title = el('h4', 'paper-title');
  const titleLink = linkButton(lbd ? p.pageUrl && p.pageUrl + '#detail' : p.posterUrl, p.title);
  if (titleLink) { titleLink.className = ''; title.append(titleLink); } else title.textContent = p.title;
  const authorsWrap = el('div', 'paper-authors-wrap');
  const authors = el('div', 'paper-authors', p.authors);
  authors.id = card.id + '-authors';
  authors.dataset.paperAuthors = '';
  const more = el('button', 'paper-authors-toggle', 'more');
  more.type = 'button';
  more.hidden = true;
  more.dataset.paperAuthorsToggle = '';
  more.setAttribute('aria-controls', authors.id);
  more.setAttribute('aria-expanded', 'false');
  more.addEventListener('click', () => {
    const opening = !card.classList.contains('authors-expanded');
    card.classList.toggle('authors-expanded', opening);
    more.setAttribute('aria-expanded', String(opening));
    more.textContent = opening ? 'less' : 'more';
  });
  authorsWrap.append(authors, more);
  copy.append(title, authorsWrap);

  const controls = el('div', 'paper-card-controls');
  const modeRow = presenterRow(p, 'presenter-mode-row', lbd
    ? { label: 'On the Wall →', title: 'Show this LBD on the LBD Wall', go: showLbdOnWall }
    : { label: 'On the Wall →', title: 'Show this paper on the Paper Wall', go: showOnWall });
  const links = paperLinks(p);
  controls.append(modeRow);
  if (links.childElementCount) controls.append(links);

  const boardHead = el('div', 'pc-paper-board-head');
  // Same light-blue overview button as Slack / PDF / Video above it.
  // An <a> so overview.css styles it exactly like those links (it styles <button> differently).
  const add = el('a', 'link-button pc-add-note', '+ Note');
  add.href = '#';
  add.setAttribute('role', 'button');
  add.dataset.add = '';
  boardHead.append(add);
  card.append(status, copy, controls, boardHead, el('div', 'pc-paper-board'));
  return card;
}

/**
 * Slack / Paper / Poster / Video. Paper, Poster and Video open the miniconf paper (or LBD) page
 * in a new tab, at that section (poster.js / lbd.js there open the section named by the #fragment).
 */
function paperLinks(p) {
  const links = el('div', 'link-row');
  const has = new Set(p.materials || []);
  const page = p.posterUrl || p.pageUrl;
  const section = id => (has.has(id) && page ? `${page}#${id}` : '');
  for (const a of [linkButton(p.channelUrl, 'Slack'), linkButton(section('paper'), 'Paper'), linkButton(section('poster'), 'Poster'), linkButton(section('video'), 'Video')]) {
    if (a) links.append(a);
  }
  return links;
}

/** Show "more" only where the author list is actually clamped (as the overview does). */
function syncAuthorOverflow(scope) {
  for (const card of scope.querySelectorAll('.live-paper-card')) {
    const authors = card.querySelector('[data-paper-authors]');
    const toggle = card.querySelector('[data-paper-authors-toggle]');
    if (card.classList.contains('authors-expanded')) { toggle.hidden = false; continue; }
    toggle.hidden = authors.scrollHeight <= authors.clientHeight + 1;
  }
}

function handleRoomError(ev) {
  if (ev.code === 'AUTH') {
    // Session expired or revoked server-side: drop the cached identity.
    app.user = null; store.set(USER_KEY, undefined); renderAuth();
    app.requireLogin('post or move notes');
  } else {
    toast(ev.message || 'Something went wrong.', { error: true });
  }
}

async function refreshCounts() {
  // Every session live (the wall is open): the counts are already here and kept current.
  if (allSessionsLive()) { scheduleBadges(); return; }
  try {
    const res = await apiFetch('/api/counts?rooms=' + encodeURIComponent(Object.keys(hall.program.sessions).join(',')), { cache: 'no-store' });
    if (!res.ok) return;
    const fresh = await res.json();
    // Live numbers from the open session win over the cached edge counts.
    const openBoards = new Set(hall.open ? hall.program.sessions[hall.open.id].papers.map(u => 'paper:' + u) : []);
    for (const [k, v] of Object.entries(fresh)) if (!openBoards.has(k)) hall.counts[k] = v;
    for (const s of Object.values(hall.program.sessions)) {
      if (hall.open?.id === s.id) continue;
      const badge = document.querySelector(`[data-session-count="${CSS.escape(s.id)}"]`);
      if (badge) badge.textContent = `${sessionNoteCount(s)} notes`;
    }
  } catch { /* badges are best effort */ }
}

// ---------- LBD hall ----------
// Every LBD shares one session (one time, one room "lbd", boards "lbd:<CMT id>"), so the hall
// has one card per group (program.lbdGroups: its theme, its count; no time, it is the same for
// all), and opening one shows its LBDs. Without groups, or while searching, every LBD shown is in
// one grid. Boards are made as their cards come near the view, so a long list costs nothing
// until it is scrolled through.
const lbdHall = { grid: null, cards: new Map(), boards: [], groups: [], open: null, match: null };
const lbdTag = n => (n.board?.startsWith('lbd:') ? 'LBD-' + n.board.slice(4) : '');
const noteCountText = n => `${n} note${n === 1 ? '' : 's'}`;

function renderLbdHall() {
  const { lbds, lbdSession } = hall.program;
  if (!lbds?.length) return;   // nothing published yet: the "Opening soon" placeholder stays
  document.querySelector('.pc-lbd-placeholder')?.remove();
  const root = $('#lbd-hall');
  const room = sessionRoom('LBD');

  const head = el('div', 'pc-lbd-head');
  const sub = el('div', 'pc-sub');
  const total = el('span', 'pc-stat', noteCountText(0));
  lbdHall.filter = uids => { lbdHall.match = uids; showLbds(); };
  sub.append(timeBlock(lbdSession, 'pc-panel-time'), el('span', 'pc-stat-sep', '·'),
    el('span', 'pc-stat', `${lbds.length} LBD${lbds.length === 1 ? '' : 's'}`), el('span', 'pc-stat-sep', '·'), total);
  // Shares the overview's card styles with an open session's grid (see build_data.py).
  const grid = lbdHall.grid = el('div', 'pc-paper-grid live-poster-paper-panel');
  grid.id = 'lbd-grid';
  const tools = el('div', 'pc-head-actions');
  tools.append(el('span', 'pc-seg-label', 'Per row'), perRowControl(grid, LBD_COLS_KEY, 'LBDs per row', () => lbdHall.boards));
  head.append(sub, tools);

  // One card per group: its theme, how many LBDs, how many notes.
  const groupCards = el('div', 'pc-session-grid pc-lbd-groups');
  const groupOf = new Map();
  lbdHall.groups = (hall.program.lbdGroups || []).map(g => {
    const card = el('button', 'pc-session-card pc-lbd-group');
    card.type = 'button';
    card.dataset.group = g.id;
    card.setAttribute('aria-expanded', 'false');
    card.setAttribute('aria-controls', 'lbd-grid');
    const notes = el('span', 'pc-stat', noteCountText(0));
    const stats = el('span', 'pc-session-stats');
    stats.append(el('span', 'pc-stat', `${g.lbds.length} LBD${g.lbds.length === 1 ? '' : 's'}`), el('span', 'pc-stat-sep', '·'), notes);
    card.append(el('span', 'pc-lbd-theme', g.theme), stats);
    card.addEventListener('click', () => openLbdGroup(lbdHall.open === g.id ? null : g.id, { scroll: true }));
    groupCards.append(card);
    for (const uid of g.lbds) groupOf.set(uid, g.id);
    return { ...g, card, notes };
  });
  lbdHall.groupOf = groupOf;

  const counters = new Map();
  const near = new IntersectionObserver(entries => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      near.unobserve(e.target);
      const l = hall.program.lbds.find(x => 'lbd-' + x.uid === e.target.id);
      const board = new BoardView(e.target.querySelector('.pc-paper-board'), {
        room, board: 'lbd:' + l.uid, title: `${l.displayId} ${l.title}`, app, fitNotes: true, dblclickExpands: true,
        emptyText: 'No notes yet: tap + Note to start the discussion',
        noteTag: lbdTag,
        // The same note also appears on the LBD Wall, beside this LBD's pin.
        createExtras: () => wallSlotFor(lbdWallLayout(), String(l.uid), [...room.notes.values()]),
      });
      lbdHall.boards.push(board);
      e.target.querySelector('[data-add]').addEventListener('click', ev => { ev.preventDefault(); board.compose(); });
    }
  }, { rootMargin: '800px 0px' });
  for (const l of lbds) {
    const card = paperCard(l, { lbd: true });
    grid.append(card);
    lbdHall.cards.set(l.uid, card);
    counters.set('lbd:' + l.uid, card.querySelector('[data-count]'));
    near.observe(card);
  }
  root.replaceChildren(...(lbdHall.groups.length ? [head, groupCards, grid] : [head, grid]));
  showLbds();

  const updateCounts = () => {
    let sum = 0;
    for (const [bid, node] of counters) {
      const n = room.countFor(bid);
      sum += n;
      node.textContent = noteCountText(n);
    }
    total.textContent = noteCountText(sum);
    for (const g of lbdHall.groups) g.notes.textContent = noteCountText(g.lbds.reduce((n, uid) => n + room.countFor('lbd:' + uid), 0));
  };
  room.subscribe(ev => {
    if (ev.type === 'error') handleRoomError(ev);
    if (['reset', 'upsert', 'remove'].includes(ev.type)) updateCounts();
  });
  if (room.ready) updateCounts();
}

/**
 * Which LBD cards the hall shows: what a search found (the group cards step aside, as the Paper
 * Hall's sessions do), else the open group's, else none until a group is opened. Without groups,
 * every LBD.
 */
function showLbds() {
  const { match, open, groups, grid } = lbdHall;
  const grouped = groups.length > 0;
  for (const g of groups) {
    g.card.setAttribute('aria-expanded', String(!match && open === g.id));
    g.card.hidden = !!match;
  }
  grid.closest('#lbd-hall')?.querySelector('.pc-lbd-groups')?.toggleAttribute('hidden', !!match);
  for (const [uid, card] of lbdHall.cards) {
    card.hidden = match ? !match.has(uid) : grouped && lbdHall.groupOf.get(uid) !== open;
  }
  grid.hidden = !match && grouped && !open;
  requestAnimationFrame(() => syncAuthorOverflow(grid));
}

/** Open one group's LBDs in the hall (null: close it). */
function openLbdGroup(id, { scroll = false } = {}) {
  lbdHall.open = id;
  showLbds();
  if (scroll && id) requestAnimationFrame(() => lbdHall.grid.scrollIntoView({ behavior: 'smooth', block: 'start' }));
}

/** Switch the LBD section between the wall (default) and the hall (one grid of cards). */
function setLbdView(view, { link = true } = {}) {
  view = view === 'hall' ? 'hall' : 'wall';
  if (view === 'hall' && lbds.wall?.frame.classList.contains('is-fullscreen')) lbds.wall.toggleFullscreen();
  lbds.view = view;
  store.set(LBD_VIEW_KEY, view);
  $('#lbd-hall').hidden = view !== 'hall';
  $('#lbd-wall').hidden = view !== 'wall';
  $('#lbd-view-title').textContent = view === 'wall' ? 'LBD Wall' : 'LBD Hall';
  document.querySelectorAll('#lbd-view button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.view === view)));
  if (view === 'wall') {
    if (lbds.wall) lbds.wall.shown();
    // One room for every LBD, shared with the hall (which already reports its errors).
    else makeLbdWall(new WallRooms(new Map([['LBD', sessionRoom('LBD')]]), () => 'LBD'));
  } else requestAnimationFrame(() => syncAuthorOverflow(lbdHall.grid));
  if (link) setLink(view === 'wall' ? '#lbdwall' : '#lbdhall');
}

function initLbdView() {
  if (!hall.program.lbds?.length) return;   // "Opening soon": no views to switch
  hall.lbdById = Object.fromEntries(hall.program.lbds.map(l => [l.uid, l]));
  renderLbdHall();
  $('#lbd-search').hidden = false;   // the LBDs' search row, with the view switch
  $('#lbd-view').addEventListener('click', e => {
    const b = e.target.closest('button[data-view]');
    if (b) setLbdView(b.dataset.view);
  });
  const shared = new URLSearchParams(location.hash.slice(1));
  setLbdView(shared.has('lbdwall') ? 'wall' : shared.has('lbdhall') ? 'hall' : store.get(LBD_VIEW_KEY, 'wall'), { link: false });
}

/** One LBD (569 = its CMT id, as lbd_569.html): on the wall, fly to its pin; in the hall, its card. */
function openLbd(uid) {
  unhide(lbds, uid);
  if (lbds.view === 'wall' && lbds.layout?.pins.has(uid)) {
    document.getElementById('lbd')?.scrollIntoView();
    lbds.wall.focusPaper(uid);
    return;
  }
  const card = lbdHall.cards.get(uid);
  if (!card) { keepInView(document.getElementById('lbd')); return; }
  const group = lbdHall.groupOf?.get(uid);
  if (!lbdHall.match && group && lbdHall.open !== group) openLbdGroup(group);
  focusCard(card);
}

// ---------- search (the miniconf's, see search.js) ----------
// One box per section, for both of its views. The walls hide what it leaves out, in place; the
// Paper Hall shows the papers found as cards instead of the sessions; the LBD Hall hides the
// other cards.
const searchItems = list => list.map(p => ({ uid: p.uid, title: p.title, keywords: p.keywords || [], authors: p.authors.split('; ').filter(a => a && a !== 'Authors TBA') }));

function initSearch() {
  const program = hall.program;
  papers.search = new SearchBox($('#paper-search'), {
    items: searchItems(program.days.flatMap(d => d.sessions.flatMap(sid => program.sessions[sid].papers.map(uid => program.papers[uid])))),
    label: 'Search papers',
    onChange: uids => {
      papers.match = uids;
      papers.wall?.setFilter(uids);
      showPaperResults(uids);
    },
  });
  if (!program.lbds?.length) return;
  lbds.search = new SearchBox($('#lbd-search'), {
    items: searchItems(program.lbds),
    label: 'Search LBDs',
    onChange: uids => {
      lbds.match = uids;
      lbds.wall?.setFilter(uids);
      lbdHall.filter?.(uids);
    },
  });
}

/** Per-row buttons for a grid of cards; `boards()` are re-fitted after a change. */
function perRowControl(grid, key, label, boards) {
  const seg = el('div', 'pc-seg');
  seg.setAttribute('role', 'group');
  seg.setAttribute('aria-label', label);
  const setCols = n => {
    store.set(key, n);
    grid.style.setProperty('--cols', n);
    requestAnimationFrame(() => syncAuthorOverflow(grid));
    seg.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(Number(b.dataset.n) === n)));
  };
  for (const n of [1, 2, 3, 4]) {
    const b = el('button', '', String(n));
    b.type = 'button'; b.dataset.n = n;
    b.addEventListener('click', () => {
      setCols(n);
      requestAnimationFrame(() => requestAnimationFrame(() => { for (const board of boards()) { board.layout(); board.fitToNotes(); } }));
    });
    seg.append(b);
  }
  setCols(store.get(key, 2));
  return seg;
}

/** Paper Hall while searching: the papers found, as cards with their boards, instead of the sessions. */
function showPaperResults(uids) {
  const old = papers.results;
  if (old) {
    old.near.disconnect();
    for (const b of old.boards) b.destroy();
    for (const off of old.unsubs) off();
    old.panel.remove();
    papers.results = null;
  }
  document.querySelectorAll('#paper-hall .pc-day-row').forEach(row => { row.hidden = !!uids; });
  if (!uids) return;
  closeSession({ keepHash: true });
  const program = hall.program;
  const found = program.days.flatMap(d => d.sessions.flatMap(sid => program.sessions[sid].papers)).filter(uid => uids.has(String(uid)));
  const panel = el('section', 'pc-session-panel pc-search-results');
  const head = el('div', 'pc-session-panel-head');
  head.append(el('h3', '', found.length ? `${found.length} paper${found.length === 1 ? '' : 's'} found` : 'No papers found'));
  // As an opened session's grid: the overview's card styles are scoped to #live-events, and no
  // session is open while searching.
  const grid = el('div', 'pc-paper-grid live-poster-paper-panel');
  grid.id = 'live-events';
  const state = { panel, boards: [], unsubs: [], near: null };
  const tools = el('div', 'pc-head-actions');
  tools.append(el('span', 'pc-seg-label', 'Per row'), perRowControl(grid, COLS_KEY, 'Papers per row', () => state.boards));
  head.append(tools);
  panel.append(head, grid);
  $('#paper-hall').append(panel);

  // Boards as their cards come near the view, as in the LBD Hall: a search can find every paper.
  state.near = new IntersectionObserver(entries => {
    for (const e of entries) {
      if (!e.isIntersecting) continue;
      state.near.unobserve(e.target);
      const uid = e.target.id.slice('paper-'.length), p = program.papers[uid];
      const room = sessionRoom(p.session);
      const board = new BoardView(e.target.querySelector('.pc-paper-board'), {
        room, board: 'paper:' + uid, title: `#${uid} ${p.title}`, app, fitNotes: true, dblclickExpands: true,
        emptyText: 'No notes yet: tap + Note to start the discussion',
        noteTag: paperTag,
        createExtras: () => wallSlotFor(wallLayout(), String(uid), [...room.notes.values()]),
      });
      state.boards.push(board);
      e.target.querySelector('[data-add]').addEventListener('click', ev => { ev.preventDefault(); board.compose(); });
    }
  }, { rootMargin: '800px 0px' });
  const counters = new Map();
  for (const uid of found) {
    const card = paperCard(program.papers[uid]);
    grid.append(card);
    counters.set('paper:' + uid, { node: card.querySelector('[data-count]'), room: sessionRoom(program.papers[uid].session) });
    state.near.observe(card);
  }
  const update = () => {
    for (const [bid, { node, room }] of counters) {
      if (!room.ready) continue;
      const n = room.countFor(bid);
      node.textContent = noteCountText(n);
    }
  };
  for (const room of new Set([...counters.values()].map(c => c.room))) {
    state.unsubs.push(room.subscribe(ev => { if (['reset', 'upsert', 'remove'].includes(ev.type)) update(); }));
  }
  update();
  papers.results = state;
  requestAnimationFrame(() => syncAuthorOverflow(grid));
}

// ---------- welcome reception ----------
function initWelcome() {
  const room = new Room('welcome');
  const board = new BoardView($('#welcome-board'), { room, board: 'welcome', title: 'Welcome Reception', app, tour: true, dblclickExpands: true, emptyText: 'Be the first to say hello: tap + Note' });
  $('#welcome-add').addEventListener('click', e => { e.preventDefault(); board.compose(); });
  $('#hero-say-hello').addEventListener('click', () => {
    $('#welcome').scrollIntoView({ behavior: 'smooth', block: 'start' });
    board.compose();
  });
  room.subscribe(ev => {
    if (ev.type === 'reset') userFromRoom(room);
    if (ev.type === 'error') handleRoomError(ev);
  });
}

function applyConference(conf) {
  const text = { name: conf.name, date: conf.date };
  document.querySelectorAll('[data-conf]').forEach(n => { if (text[n.dataset.conf]) n.textContent = text[n.dataset.conf]; });
  // The Live Overview is the miniconf's other add-on, at {prefix}/live.html (live_overview/).
  const prefix = conf.miniconfUrl ? conf.miniconfUrl.replace(/\/+$/, '') : '';
  const links = { miniconf: prefix ? prefix + '/' : '', live: prefix ? prefix + '/live.html' : '', official: conf.officialSiteUrl };
  document.querySelectorAll('[data-site-link]').forEach(a => { if (/^https:\/\//.test(links[a.dataset.siteLink] || '')) a.href = links[a.dataset.siteLink]; });
  const help = $('#helpdesk-link');
  if (/^https:\/\//.test(conf.helpdeskUrl || '')) help.href = conf.helpdeskUrl; else help.remove();
}

// ---------- boot ----------
async function main() {
  const handoff = takeTokenFromHash();
  if (handoff) { location.replace(handoff); return; }
  // Sign-in can arrive without a page load: Safari may only change the #fragment of an open
  // page ("Open in Safari" from another app), or restore the page from its back/forward cache.
  // Either way the page would still look signed out, so pick the session up and reload.
  window.addEventListener('hashchange', () => {
    if (!/(^#|&)(pc_auth|pc_link)=/.test(location.hash)) return;
    const next = takeTokenFromHash();
    if (next) location.replace(next); else location.reload();
  });
  window.addEventListener('pageshow', e => { if (e.persisted) location.reload(); });
  // Signed in or out on the Live Overview, or in another tab: so here too. Reload, so that every
  // live connection reopens with (or without) the session.
  onSessionChange(() => location.reload());
  renderAuth();
  const params = new URLSearchParams(location.search);
  if (params.get('login_error')) {
    toast(params.get('login_error').slice(0, 160), { error: true, ms: 8000 });
    params.delete('login_error');
    history.replaceState(null, '', location.pathname + (params.toString() ? '?' + params : '') + location.hash);
  }
  // The paper data and the sign-in check travel in parallel. Nothing waits for the check: the
  // page shows the remembered name meanwhile, and the server checks every write anyway.
  const programReady = fetch(new URL('./data/program.json', import.meta.url)).then(r => r.json());
  const userReady = refreshUser();
  // The Canon easter egg (canon-egg.js, a classic script) records solves through these.
  window.PC_EGG = {
    get user() { return app.user; },
    login: () => app.login(),
    solve: () => apiFetch('/api/egg/solve', { method: 'POST' }).then(r => r.json()),
    leaderboard: () => apiFetch('/api/egg/leaderboard', { cache: 'no-store' }).then(r => r.json()),
  };
  userReady.then(() => window.dispatchEvent(new Event('pc-egg-ready')));
  initWelcome();

  // Relative to this module, so it resolves on the Worker and in the GitHub Pages build alike.
  const program = await programReady;
  hall.program = program;
  const snapshotReady = loadSnapshot();   // in flight while the hall and wall are built
  window.PC_PROGRAM = program; // read by canon-egg.js for paper fun facts
  applyConference(program.conference);
  renderHall();
  initPaperView();
  initLbdView();
  initSearch();
  refreshSessionTimes();
  window.addEventListener('ismir-timezone-change', refreshSessionTimes);
  let cardsWidth = window.innerWidth;   // the author lists only re-wrap when the width changes
  window.addEventListener('resize', () => {
    if (window.innerWidth === cardsWidth) return;
    cardsWidth = window.innerWidth;
    if (hall.open) syncAuthorOverflow(hall.open.panel);
    if (papers.results) syncAuthorOverflow(papers.results.panel);
    if (lbdHall.grid) syncAuthorOverflow(lbdHall.grid);
  });
  // Session badges: refresh every 20 s while the page is visible, and at once when it comes
  // back to the foreground (another tab, another app, a phone waking up).
  snapshotReady.then(refreshCounts);
  setInterval(() => { if (!document.hidden) refreshCounts(); }, 20_000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshCounts(); });
  window.addEventListener('focus', refreshCounts);

  // Deep links (see setLink): go there now, and whenever the #fragment changes.
  route();
  window.addEventListener('hashchange', () => { if (!/(^#|&)(pc_auth|pc_link)=/.test(location.hash)) route(); });

  setInterval(() => {
    document.querySelectorAll('.pc-note-time[data-ts]').forEach(n => {
      const edited = n.textContent.endsWith(' · edited') ? ' · edited' : '';
      n.textContent = timeAgo(Number(n.dataset.ts)) + edited;
    });
  }, 60_000);
}

main();
