// The Paper Wall: one big board showing every paper at once, an alternative to the Paper Hall.
// The LBD Wall is the same for the Late-Breaking Demos (app.js): one area for all of them, or one
// per group should LBDs get groups.
//
// Papers are pinned cards (fixed, nobody can move them), laid out like the hall: one area per
// session, and inside each area the papers in two rows (LBD Wall: as many rows as fit the screen
// best). Notes sit around their paper's pin. A note on the wall is the same note as on the paper's own board (same server
// object, so edits and deletes show in both views); only its position differs: x/y on the paper
// board, wx/wy (an offset from the paper's pin) on the wall. See WALL_REACH in board-core.js.

import { BoardView, NOTE_W, el } from './board.js';

// Logical wall units (the same units as note sizes: a note is NOTE_W wide).
const PIN_W = 340, PIN_H = 260;
const CELL_W = 680, CELL_H = 540;          // one paper: its pin plus room for notes around it
const PIN_IN_CELL = { x: 40, y: 40 };
const REGION_PAD = 50, REGION_HEAD = 260;  // a session area: padding and its title band
const GAP = 150, MARGIN = 150;             // between session areas / around the wall
const PAPER_ROWS = 2;
const NOTE_H = 128;                        // footprint used when finding a free spot
const SLOT_GAP = 20;

/**
 * What a wall shows (app.js builds one for papers and one for LBDs):
 *   prefix  the notes' board prefix: 'paper' (boards paper:<uid>) or 'lbd' (lbd:<uid>)
 *   groups  its areas in order: { id, uids, ...anything regionHead needs }, e.g. one per session
 *   rows    rows of papers in each area: a number, or 'fit' for whatever fills the screen best
 *   head    optional: the height of each area's title band (default REGION_HEAD)
 */

/**
 * Where every area and pin goes: groups in order (as in the hall), `perRow` areas to a row and
 * `rows` rows of papers in each. Note positions on the wall are offsets from their paper's pin,
 * so the areas can be arranged differently on every screen and notes still follow their papers.
 */
function placeWall(spec, perRow, rows) {
  const regions = [], pins = new Map();
  const groups = spec.groups.filter(g => g.uids.length);
  // Every area has the same shape, columns and rows (those of the largest), so areas line up and
  // match; a smaller one just has a shorter last row.
  const most = Math.max(1, ...groups.map(g => g.uids.length));
  const cols = Math.ceil(most / rows), r = Math.ceil(most / cols);
  let x = MARGIN, y = MARGIN, rowH = 0, width = 0;
  groups.forEach((g, n) => {
    if (n && n % perRow === 0) { y += rowH + GAP; x = MARGIN; rowH = 0; }
    const head = spec.head || REGION_HEAD;
    const w = REGION_PAD * 2 + cols * CELL_W, h = REGION_PAD * 2 + head + r * CELL_H;
    regions.push({ ...g, x, y, w, h });
    g.uids.forEach((uid, i) => {
      const cell = { x: x + REGION_PAD + (i % cols) * CELL_W, y: y + REGION_PAD + head + Math.floor(i / cols) * CELL_H, w: CELL_W, h: CELL_H };
      pins.set(String(uid), { uid: String(uid), group: g.id, x: cell.x + PIN_IN_CELL.x, y: cell.y + PIN_IN_CELL.y, w: PIN_W, h: PIN_H, cell });
    });
    x += w + GAP;
    width = Math.max(width, x - GAP + MARGIN);
    rowH = Math.max(rowH, h);
  });
  return { W: Math.max(width, 2000), H: Math.max(y + rowH + MARGIN, 1000), regions, pins, perRow, rows, prefix: spec.prefix };
}

/**
 * The wall laid out for a screen of shape `aspect` (width / height of the expanded view): the
 * number of areas per row (and, for rows: 'fit', of rows of papers) whose wall shape comes
 * closest, so an expanded wall fills tall phones, tablets and ultra-wide monitors alike.
 */
export function buildWallLayout(spec, aspect = 2.2) {
  const groups = spec.groups.filter(g => g.uids.length);
  const most = Math.max(1, ...groups.map(g => g.uids.length));
  const rowChoices = spec.rows === 'fit' ? Array.from({ length: most }, (_, i) => i + 1) : [spec.rows || PAPER_ROWS];
  let best = null;
  for (let perRow = 1; perRow <= Math.max(1, groups.length); perRow++) {
    for (const rows of rowChoices) {
      const layout = placeWall(spec, perRow, rows);
      const miss = Math.abs(Math.log(layout.W / layout.H) - Math.log(aspect));
      if (!best || miss < best.miss - 1e-9) best = { layout, miss };
    }
  }
  return best.layout;
}

/** Same arrangement? (A resize only rebuilds the wall when it would change.) */
export const sameLayout = (a, b) => !!a && !!b && a.perRow === b.perRow && a.rows === b.rows;

/** Shape (width / height) of the wall's expanded view in this window. */
export function screenAspect() {
  // The expanded board: the window minus its margins, the board's title bar and the search bar
  // under it.
  return Math.max(200, window.innerWidth - 28) / Math.max(200, window.innerHeight - 144);
}

/** The paper (or LBD) uid a note belongs to on this wall; '' for notes from elsewhere. */
const uidIn = (layout, note) => {
  const prefix = layout.prefix + ':';
  return typeof note.board === 'string' && note.board.startsWith(prefix) ? note.board.slice(prefix.length) : '';
};
const hits = (a, b, pad = 0) => a.x < b.x + b.w + pad && b.x < a.x + a.w + pad && a.y < b.y + b.h + pad && b.y < a.y + a.h + pad;

/**
 * A free spot for a new note beside paper `uid`, as an offset from its pin: the nearest place
 * around the pin that covers no pin and no note in `taken` (absolute rects).
 */
export function freeWallSlot(layout, uid, taken) {
  const pin = layout.pins.get(uid);
  if (!pin) return { wx: PIN_W + SLOT_GAP, wy: 0 };
  const sx = NOTE_W + SLOT_GAP, sy = NOTE_H;
  const pinRect = { x: pin.x, y: pin.y, w: PIN_W, h: PIN_H };
  const near = [...layout.pins.values()].filter(p => Math.abs(p.x - pin.x) < CELL_W * 3 && Math.abs(p.y - pin.y) < CELL_H * 3);
  const candidates = [];
  // A lattice anchored just right of the pin, so the first column hugs the card.
  for (let i = -4; i <= 5; i++) {
    for (let j = -3; j <= 7; j++) {
      const wx = PIN_W + SLOT_GAP + (i - 1) * sx, wy = j * sy;
      const rect = { x: pin.x + wx, y: pin.y + wy, w: NOTE_W, h: NOTE_H };
      if (rect.x < 0 || rect.y < 0 || rect.x + rect.w > layout.W || rect.y + rect.h > layout.H) continue;
      if (hits(rect, pinRect, 12)) continue;
      // Nearest first; to the right and below the pin before left and above.
      const dx = rect.x + rect.w / 2 - (pin.x + PIN_W / 2), dy = rect.y + rect.h / 2 - (pin.y + PIN_H / 2);
      candidates.push({ wx, wy, rect, d: Math.hypot(dx * (dx < 0 ? 1.6 : 1), dy * (dy < 0 ? 2.2 : 1.5)) });
    }
  }
  candidates.sort((a, b) => a.d - b.d);
  for (const c of candidates) {
    if (near.some(p => hits(c.rect, p, 12))) continue;
    if (taken.some(t => hits(c.rect, t))) continue;
    return { wx: c.wx, wy: c.wy };
  }
  // Crowded: stack loosely to the right of the pin.
  return { wx: PIN_W + SLOT_GAP + Math.round(Math.random() * 60), wy: Math.round(Math.random() * 120) };
}

/**
 * Absolute wall positions of `notes`. Notes from before the wall have no wx/wy: they get the
 * free spots around their pin in the order they were written, so every viewer sees the same
 * layout. They only avoid each other (and pins), so new notes never push them around.
 */
export function wallPositions(layout, notes) {
  const out = new Map();
  const legacy = new Map();
  for (const n of notes) {
    const uid = uidIn(layout, n), pin = layout.pins.get(uid);
    if (!pin) continue;
    if (Number.isFinite(n.wx) && Number.isFinite(n.wy)) out.set(n.id, { x: pin.x + n.wx, y: pin.y + n.wy });
    else (legacy.get(uid) || legacy.set(uid, []).get(uid)).push(n);
  }
  for (const [uid, list] of legacy) {
    const pin = layout.pins.get(uid), taken = [];
    list.sort((a, b) => (a.created - b.created) || (a.id < b.id ? -1 : 1));
    for (const n of list) {
      const { wx, wy } = freeWallSlot(layout, uid, taken);
      const p = { x: pin.x + wx, y: pin.y + wy };
      taken.push({ ...p, w: NOTE_W, h: NOTE_H });
      out.set(n.id, p);
    }
  }
  return out;
}

/** Where a note new to paper `uid` goes on the wall, given the notes we can see. */
export function wallSlotFor(layout, uid, notes) {
  const taken = [...wallPositions(layout, notes).values()].map(p => ({ ...p, w: NOTE_W, h: NOTE_H }));
  return freeWallSlot(layout, uid, taken);
}

/** A free spot near the middle of a paper board (W x H) for a note started on the wall. */
export function freeBoardSpot(notes, W, H) {
  const sx = NOTE_W + SLOT_GAP, sy = 170;
  const taken = notes.map(n => ({ x: n.x, y: n.y, w: NOTE_W, h: 150 }));
  const x0 = W / 2 - NOTE_W / 2, y0 = H / 2 - 75;
  for (let ring = 0; ring < 12; ring++) {
    for (let i = -ring; i <= ring; i++) {
      for (let j = -ring; j <= ring; j++) {
        if (Math.max(Math.abs(i), Math.abs(j)) !== ring) continue;
        const r = { x: x0 + i * sx, y: y0 + j * sy, w: NOTE_W, h: 150 };
        if (r.x < 0 || r.y < 0 || r.x + r.w > W || r.y + r.h > H) continue;
        if (!taken.some(t => hits(r, t))) return { x: Math.round(r.x), y: Math.round(r.y) };
      }
    }
  }
  return { x: Math.round(x0), y: Math.round(y0) };
}

/**
 * Several rooms at once (every poster session's), presented to BoardView as one room: a merged
 * note map, events passed through, and each message routed to the room that owns the note.
 * `rooms` maps a key to its Room (app.js shares them with the hall, so each session has one
 * connection); `keyForCreate(msg)` names the room a new note goes to.
 */
export class WallRooms {
  constructor(rooms, keyForCreate) {
    this.keyForCreate = keyForCreate;
    this.notes = new Map();
    this.owner = new Map();
    this.me = null;
    this.limits = { boardW: 2000, boardH: 1000, expand: 1, textMax: 600 };
    this.paperLimits = { boardW: 4000, boardH: 2480 };
    this.listeners = new Set();
    this.rooms = rooms;
    this.unsubs = [];
    this.resetFrame = 0;
    for (const room of rooms.values()) {
      this.unsubs.push(room.subscribe(ev => this.onRoom(room, ev)));
      if (room.ready) this.onRoom(room, { type: 'reset' });   // already live (opened by the hall)
    }
  }

  get ready() { return [...this.rooms.values()].some(r => r.ready); }

  subscribe(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
  emit(ev) { for (const fn of this.listeners) { try { fn(ev); } catch (e) { console.error(e); } } }

  onRoom(room, ev) {
    if (ev.type === 'reset') {
      for (const [id, owner] of this.owner) if (owner === room) { this.owner.delete(id); this.notes.delete(id); }
      for (const n of room.notes.values()) { this.notes.set(n.id, n); this.owner.set(n.id, room); }
      if (room.me) this.me = room.me;
      if (room.limits?.textMax) this.limits.textMax = room.limits.textMax;
      if (room.limits?.boardW) this.paperLimits = { boardW: room.limits.boardW, boardH: room.limits.boardH };
      // Fourteen rooms answer within moments of each other: redraw once per frame, not per room.
      this.resetFrame ||= requestAnimationFrame(() => { this.resetFrame = 0; this.emit({ type: 'reset' }); });
      return;
    } else if (ev.type === 'upsert') {
      if (ev.replaces) { this.notes.delete(ev.replaces); this.owner.delete(ev.replaces); }
      this.notes.set(ev.note.id, ev.note); this.owner.set(ev.note.id, room);
    } else if (ev.type === 'remove') {
      this.notes.delete(ev.note.id); this.owner.delete(ev.note.id);
    }
    this.emit(ev);
  }

  roomFor(msg) {
    if (msg.t === 'create') return this.rooms.get(this.keyForCreate(msg));
    return this.owner.get(msg.id);
  }

  raw(msg) { return !!this.roomFor(msg)?.raw(msg); }

  send(msg) {
    const room = this.roomFor(msg);
    if (room) return room.send(msg);
    this.emit({ type: 'error', code: 'GONE', message: 'That note no longer exists.' });
    return false;
  }

  /** Stop listening. The rooms stay open: they belong to app.js and serve the hall too. */
  close() {
    cancelAnimationFrame(this.resetFrame);
    for (const off of this.unsubs) off();
    this.listeners.clear();
  }
}

/**
 * The wall itself: BoardView's camera, notes and dragging, with pins drawn underneath and note
 * positions read from wx/wy. From app.js: `layout` (buildWallLayout), `items` (uid -> paper or
 * LBD), `buildPin(item)` makes a pin's card and `regionHead(region)` an area's title band.
 */
export class WallView extends BoardView {
  constructor(mount, o) {
    // Embedded, a double-click expands the wall (as on the other boards); expanded, it starts a note.
    super(mount, { ...o, board: null, title: o.title || 'Paper Wall', emptyText: '', dblclickExpands: true });
    this.frame.classList.add('pc-wall-frame');
    this.frame.style.setProperty('--wall-ratio', String(this.W / this.H));
    this.titleBar.querySelectorAll('.pc-fullscreen-hint').forEach(n => n.remove());
    this.titleBar.append(el('div', 'pc-fullscreen-hint', 'Comment on a paper, or double-click beside it to leave a note'));
    this.zoomLabel.title = 'Show the whole wall';
    this.zoomLabel.setAttribute('aria-label', 'Show the whole wall');
    this.buildWall();
    this.layout(true);
  }

  get wall() { return this.opts.layout; }
  get W() { return this.opts.layout.W; }
  get H() { return this.opts.layout.H; }

  owns(n) { return this.opts.layout.pins.has(uidIn(this.wall, n)); }

  filteredOut(n) { return !!this.filter && !this.filter.has(uidIn(this.wall, n)); }

  /**
   * Show only the papers in `uids` (a Set; null shows all) and their notes. Nothing moves: the
   * others are just hidden, so clearing the search puts the wall back as it was.
   */
  setFilter(uids, { fit = true } = {}) {
    this.filter = uids || null;
    for (const pin of this.surface.querySelectorAll('.pc-pin')) pin.classList.toggle('pc-filtered-out', !!this.filter && !this.filter.has(pin.dataset.uid));
    for (const [id, node] of this.els) {
      const n = this.room.notes.get(id);
      if (n) node.classList.toggle('pc-filtered-out', this.filteredOut(n));
    }
    if (fit) this.fitFilter();
  }

  /** Glide to just what the search shows, its papers and their notes; no search: the whole wall. */
  fitFilter() {
    if (!this.scroller.clientWidth) { this.pendingFit = true; return; }   // hidden (the hall is shown): see shown()
    this.pendingFit = false;
    if (!this.filter) { this.glideTo(this.fitCamera()); return; }
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    const add = (x, y, w, h) => { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x + w); y1 = Math.max(y1, y + h); };
    for (const uid of this.filter) {
      const pin = this.wall.pins.get(uid);
      if (pin) add(pin.x, pin.y, pin.w, pin.h);
    }
    for (const node of this.els.values()) {
      if (node.classList.contains('pc-filtered-out')) continue;
      add(parseFloat(node.style.left) || 0, parseFloat(node.style.top) || 0, node._w || NOTE_W, node._h || NOTE_H);
    }
    if (x0 === Infinity) return;   // nothing found: stay where you are
    this.glideTo(this.frameRect({ x: x0, y: y0, w: x1 - x0, h: y1 - y0 }, 1.12));
  }

  notePos(n) {
    const pin = this.opts.layout.pins.get(uidIn(this.wall, n));
    if (Number.isFinite(n.wx) && Number.isFinite(n.wy)) return { x: pin.x + n.wx, y: pin.y + n.wy };
    // Older notes: computed spots, the same for every viewer.
    return wallPositions(this.opts.layout, [...this.room.notes.values()].filter(m => uidIn(this.wall, m) === uidIn(this.wall, n))).get(n.id) || { x: pin.x + PIN_W + SLOT_GAP, y: pin.y };
  }

  sendMove(final, id, x, y) {
    const n = this.room.notes.get(id), pin = n && this.wall.pins.get(uidIn(this.wall, n));
    if (!pin) return false;
    const msg = { t: final ? 'wmove' : 'wdrag', id, wx: Math.round(x - pin.x), wy: Math.round(y - pin.y) };
    return final ? this.room.send(msg) : this.room.raw(msg);
  }

  isPanTarget(target) {
    if (target === this.surface || target === this.empty) return true;
    // Pins and session areas are part of the wall: dragging them pans, except their links.
    return !!target.closest?.('.pc-wall-layer') && !target.closest('a, button');
  }

  updateEmpty() { this.empty.hidden = true; }

  /** Expanded, the wall fills the window, whatever its shape, and zooms out to show all of itself. */
  fitScale(width, height, full) { return full ? Math.min(width / this.W, height / this.H) : width / this.W; }

  /** The wall's default view: all of it. */
  fitCamera() { return { s: this.minScale, cx: this.W / 2, cy: this.H / 2 }; }

  onRoom(ev) {
    if (ev.type === 'drag') return;   // a move on a paper board, not here
    if (ev.type === 'wdrag') {
      const n = this.room.notes.get(ev.id), pin = n && this.wall.pins.get(uidIn(this.wall, n));
      if (!pin) return;
      super.onRoom({ type: 'drag', id: ev.id, x: pin.x + ev.wx, y: pin.y + ev.wy });
      return;
    }
    super.onRoom(ev);
  }

  // Session areas lie under the notes; pins lie above every note (pc-wall-pins in styles.css),
  // so however notes are moved, no paper is ever covered.
  buildWall() {
    const layer = el('div', 'pc-wall-layer');
    const pins = el('div', 'pc-wall-layer pc-wall-pins');
    const { items, buildPin, regionHead } = this.opts;
    for (const r of this.wall.regions) {
      const box = el('section', 'pc-wall-region');
      Object.assign(box.style, { left: r.x + 'px', top: r.y + 'px', width: r.w + 'px', height: r.h + 'px' });
      const head = regionHead(r);
      head.classList.add('pc-wall-region-head');
      head.title = 'Zoom to this area';
      head.addEventListener('click', () => this.glideTo(this.frameRect(r)));
      head.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this.glideTo(this.frameRect(r)); } });
      box.append(head);
      layer.append(box);
    }
    for (const pin of this.wall.pins.values()) {
      const card = buildPin(items[pin.uid]);
      card.classList.add('pc-pin');
      card.dataset.uid = pin.uid;
      Object.assign(card.style, { left: pin.x + 'px', top: pin.y + 'px', width: PIN_W + 'px', height: PIN_H + 'px' });
      card.querySelector('[data-comment]')?.addEventListener('click', e => { e.preventDefault(); this.commentOn(pin.uid); });
      card.addEventListener('dblclick', e => {
        e.stopPropagation();
        if (!this.frame.classList.contains('is-fullscreen')) this.expandAt(e);
      });
      pins.append(card);
    }
    this.surface.prepend(layer);
    this.surface.append(pins);
  }

  // A relayout (e.g. the session rooms arriving right after a deep link) cancels a glide in
  // flight; finish it instead of stopping halfway.
  glideTo(to) {
    this.glide = { to, until: performance.now() + 500 };
    super.glideTo(to);
  }

  layout(force) {
    const pending = this.glide && performance.now() < this.glide.until ? this.glide.to : null;
    super.layout(force);
    if (pending) this.glideTo(pending);
  }

  /** Shown again after the hall: notes laid out while hidden need measuring. */
  shown() {
    this.renderAll();
    this.layout(true);
    if (this.pendingFit) this.fitFilter();
  }

  /** Camera that frames rect r (with a margin). */
  frameRect(r, margin = 1.08) {
    const vw = this.scroller.clientWidth, vh = this.scroller.clientHeight;
    return { s: this.clampScale(Math.min(vw / (r.w * margin), vh / (r.h * margin))), cx: r.x + r.w / 2, cy: r.y + r.h / 2 };
  }

  /** Glide to one area, e.g. a session's (deep links). */
  focusSession(id) {
    const r = this.wall.regions.find(r => r.id === id);
    if (r) this.glideTo(this.frameRect(r));
  }

  /** Glide to one paper at 1000%, its pin in the middle of the view (deep links, "On the Wall"). */
  focusPaper(uid) {
    const pin = this.wall.pins.get(String(uid));
    if (!pin) return;
    // Start once the wall has its final size (it may have just been shown), or the first
    // relayout would nudge the zoom back mid-glide.
    requestAnimationFrame(() => requestAnimationFrame(() => {
      this.glideTo({ s: this.clampScale(this.base * 10), cx: pin.x + pin.w / 2, cy: pin.y + pin.h / 2 });
    }));
    const card = this.surface.querySelector(`.pc-pin[data-uid="${CSS.escape(String(uid))}"]`);
    card?.classList.add('pc-paper-focus');
    setTimeout(() => card?.classList.remove('pc-paper-focus'), 2600);
  }

  /** Double-click on the wall: a note for the paper whose area was clicked, right there. */
  compose(x, y) {
    if (x === undefined) return;
    const cx = x + NOTE_W / 2, cy = y + 20;
    const pin = [...this.wall.pins.values()].find(p => cx >= p.cell.x && cx < p.cell.x + p.cell.w && cy >= p.cell.y && cy < p.cell.y + p.cell.h);
    if (!pin) { this.app.toast?.('Double-click beside a paper to leave a note on it.'); return; }
    this.commentOn(pin.uid, { x, y });
  }

  /** New note on paper `uid`: beside its pin (or at `at`), and on the paper's own board. */
  async commentOn(uid, at) {
    this.stopTour();
    if (!this.app.requireLogin('post a note')) return;
    const paper = this.opts.items[uid], board = `${this.wall.prefix}:${uid}`;
    if (this.app.beforeNote && !(await this.app.beforeNote(board))) return;
    const result = await this.app.composer.open({ heading: 'New note', where: `${paper.displayId || '#' + uid} ${paper.title}`, max: this.room.limits.textMax });
    if (!result) return;
    const pin = this.wall.pins.get(uid);
    const notes = [...this.room.notes.values()];
    const slot = at
      ? { wx: Math.round(Math.min(Math.max(0, at.x), this.W - NOTE_W) - pin.x), wy: Math.round(Math.min(Math.max(0, at.y), this.H - 160) - pin.y) }
      : wallSlotFor(this.wall, uid, notes);
    const { boardW, boardH } = this.room.paperLimits;
    const spot = freeBoardSpot(notes.filter(n => n.board === board), boardW, boardH);
    this.room.send({ t: 'create', board, text: result.text, color: result.color, ...spot, ...slot });
  }

  destroy({ keepRooms = false } = {}) {
    super.destroy();
    if (!keepRooms) this.room.close();
  }
}

