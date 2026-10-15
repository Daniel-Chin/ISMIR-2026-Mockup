// The Paper Wall: one big board showing every paper at once, an alternative to the Paper Hall.
//
// Papers are pinned cards (fixed, nobody can move them), laid out like the hall: one row of
// sessions per day, and inside each session area the papers in two rows. Notes sit around their
// paper's pin. A note on the wall is the same note as on the paper's own board (same server
// object, so edits and deletes show in both views); only its position differs: x/y on the paper
// board, wx/wy (an offset from the paper's pin) on the wall. See WALL_REACH in board-core.js.

import { Room } from './room.js';
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

/** Where every session area and pin goes. Pure function of program.json. */
export function buildWallLayout(program) {
  const regions = [], pins = new Map();
  let y = MARGIN, width = 0;
  for (const day of program.days) {
    let x = MARGIN, rowH = 0;
    for (const sid of day.sessions) {
      const s = program.sessions[sid];
      if (!s?.papers.length) continue;
      const cols = Math.ceil(s.papers.length / PAPER_ROWS);
      const w = REGION_PAD * 2 + cols * CELL_W, h = REGION_PAD * 2 + REGION_HEAD + PAPER_ROWS * CELL_H;
      regions.push({ id: sid, day: day.day, x, y, w, h });
      s.papers.forEach((uid, i) => {
        const cell = { x: x + REGION_PAD + (i % cols) * CELL_W, y: y + REGION_PAD + REGION_HEAD + Math.floor(i / cols) * CELL_H, w: CELL_W, h: CELL_H };
        pins.set(String(uid), { uid: String(uid), session: sid, x: cell.x + PIN_IN_CELL.x, y: cell.y + PIN_IN_CELL.y, w: PIN_W, h: PIN_H, cell });
      });
      x += w + GAP;
      rowH = Math.max(rowH, h);
    }
    if (!rowH) continue;
    width = Math.max(width, x - GAP + MARGIN);
    y += rowH + GAP;
  }
  return { W: Math.max(width, 2000), H: Math.max(y - GAP + MARGIN, 1000), regions, pins };
}

const uidOf = note => (typeof note.board === 'string' && note.board.startsWith('paper:') ? note.board.slice(6) : '');
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
    const uid = uidOf(n), pin = layout.pins.get(uid);
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
 * Every session room at once, presented to BoardView as one room: a merged note map, events
 * passed through, and each message routed to the room that owns the note.
 */
export class WallRooms {
  constructor(program) {
    this.program = program;
    this.notes = new Map();
    this.owner = new Map();
    this.me = null;
    this.limits = { boardW: 2000, boardH: 1000, expand: 1, textMax: 600 };
    this.paperLimits = { boardW: 4000, boardH: 2480 };
    this.listeners = new Set();
    this.rooms = new Map();
    for (const sid of Object.keys(program.sessions)) {
      const room = new Room('session:' + sid);
      this.rooms.set(sid, room);
      room.subscribe(ev => this.onRoom(room, ev));
    }
  }

  subscribe(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
  emit(ev) { for (const fn of this.listeners) { try { fn(ev); } catch (e) { console.error(e); } } }

  onRoom(room, ev) {
    if (ev.type === 'reset') {
      for (const [id, owner] of this.owner) if (owner === room) { this.owner.delete(id); this.notes.delete(id); }
      for (const n of room.notes.values()) { this.notes.set(n.id, n); this.owner.set(n.id, room); }
      if (room.me) this.me = room.me;
      if (room.limits?.textMax) this.limits.textMax = room.limits.textMax;
      if (room.limits?.boardW) this.paperLimits = { boardW: room.limits.boardW, boardH: room.limits.boardH };
    } else if (ev.type === 'upsert') {
      this.notes.set(ev.note.id, ev.note); this.owner.set(ev.note.id, room);
    } else if (ev.type === 'remove') {
      this.notes.delete(ev.note.id); this.owner.delete(ev.note.id);
    }
    this.emit(ev);
  }

  roomFor(msg) {
    if (msg.t === 'create') return this.rooms.get(this.program.papers[uidOf(msg)]?.session);
    return this.owner.get(msg.id);
  }

  raw(msg) { return !!this.roomFor(msg)?.raw(msg); }

  send(msg) {
    const room = this.roomFor(msg);
    if (room) return room.send(msg);
    this.emit({ type: 'error', code: 'GONE', message: 'That note no longer exists.' });
    return false;
  }

  close() {
    for (const room of this.rooms.values()) room.close();
    this.listeners.clear();
  }
}

/**
 * The wall itself: BoardView's camera, notes and dragging, with pins drawn underneath and note
 * positions read from wx/wy. `buildPin(paper)` (app.js) makes a pin's card.
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

  owns(n) { return this.opts.layout.pins.has(uidOf(n)); }

  notePos(n) {
    const pin = this.opts.layout.pins.get(uidOf(n));
    if (Number.isFinite(n.wx) && Number.isFinite(n.wy)) return { x: pin.x + n.wx, y: pin.y + n.wy };
    // Older notes: computed spots, the same for every viewer.
    return wallPositions(this.opts.layout, [...this.room.notes.values()].filter(m => uidOf(m) === uidOf(n))).get(n.id) || { x: pin.x + PIN_W + SLOT_GAP, y: pin.y };
  }

  sendMove(final, id, x, y) {
    const n = this.room.notes.get(id), pin = n && this.wall.pins.get(uidOf(n));
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

  /** The wall's default view: all of it. */
  fitCamera() { return { s: this.minScale, cx: this.W / 2, cy: this.H / 2 }; }

  onRoom(ev) {
    if (ev.type === 'drag') return;   // a move on a paper board, not here
    if (ev.type === 'wdrag') {
      const n = this.room.notes.get(ev.id), pin = n && this.wall.pins.get(uidOf(n));
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
    const { program, buildPin, regionHead } = this.opts;
    for (const r of this.wall.regions) {
      const box = el('section', 'pc-wall-region');
      Object.assign(box.style, { left: r.x + 'px', top: r.y + 'px', width: r.w + 'px', height: r.h + 'px' });
      const head = regionHead(program.sessions[r.id], r);
      head.classList.add('pc-wall-region-head');
      head.title = 'Zoom to this session';
      head.addEventListener('click', () => this.glideTo(this.frameRect(r)));
      head.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); this.glideTo(this.frameRect(r)); } });
      box.append(head);
      layer.append(box);
    }
    for (const pin of this.wall.pins.values()) {
      const card = buildPin(program.papers[pin.uid]);
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

  // Expand / Collapse keep what you are looking at (same spot, same zoom) instead of jumping
  // back to the whole wall: on a wall this big, the spot is what matters.
  toggleFullscreen({ keepView = false } = {}) {
    const before = keepView ? null : this.camera();
    super.toggleFullscreen({ keepView: true });
    if (before) this.setCamera(this.reachable(before));
  }

  /** Shown again after the hall: notes laid out while hidden need measuring. */
  shown() {
    this.renderAll();
    this.layout(true);
  }

  /** Camera that frames rect r (with a margin). */
  frameRect(r, margin = 1.08) {
    const vw = this.scroller.clientWidth, vh = this.scroller.clientHeight;
    return { s: this.clampScale(Math.min(vw / (r.w * margin), vh / (r.h * margin))), cx: r.x + r.w / 2, cy: r.y + r.h / 2 };
  }

  /** Glide to one session's area (deep links). */
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
    const paper = this.opts.program.papers[uid];
    const result = await this.app.composer.open({ heading: 'New note', where: `${paper.displayId || '#' + uid} ${paper.title}`, max: this.room.limits.textMax });
    if (!result) return;
    const pin = this.wall.pins.get(uid);
    const notes = [...this.room.notes.values()];
    const slot = at
      ? { wx: Math.round(Math.min(Math.max(0, at.x), this.W - NOTE_W) - pin.x), wy: Math.round(Math.min(Math.max(0, at.y), this.H - 160) - pin.y) }
      : wallSlotFor(this.wall, uid, notes);
    const { boardW, boardH } = this.room.paperLimits;
    const spot = freeBoardSpot(notes.filter(n => n.board === 'paper:' + uid), boardW, boardH);
    this.room.send({ t: 'create', board: 'paper:' + uid, text: result.text, color: result.color, ...spot, ...slot });
  }

  destroy() {
    super.destroy();
    this.room.close();
  }
}

export { uidOf };
