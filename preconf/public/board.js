// A scalable corkboard bound to one board id inside a Room.
// All user text goes through textContent; nothing from the server is parsed as HTML.

const NOTE_W = 230;            // default width; short notes keep it
const NOTE_W_MAX = 680;        // widest a long note may grow (600 chars fit well below this)
const NOTE_RATIO_MIN = 0.5;    // a long note's height / width lands in [0.5, 1)
// Width only changes the height in whole wrapped lines, so the fitted ratio can undershoot its
// target by up to one line (about 18px / 230px). Aim that much higher to stay inside the range.
const NOTE_RATIO_SLACK = 0.08;

/** Stable 0..1 from a note id, so every viewer picks the same shape for the same note. */
function idFraction(id) {
  let h = 2166136261;
  for (let i = 0; i < id.length; i++) h = Math.imul(h ^ id.charCodeAt(i), 16777619);
  return (h >>> 0) / 4294967296;
}
const DRAG_SEND_MS = 70;
const MAX_SCALE = 3;           // absolute: notes at 3x their logical size
// The fitted "all notes" view zooms in at most 2x (in width and height) past the whole-board
// view, i.e. no closer than 100%: a lone note should not blow up to fill the screen.
const FIT_MAX_ZOOM = 2;
const TOUR_MOVE_MS = 4500;     // intro camera: one glide between shots
const TOUR_HOLD_MS = 2200;     // ...then rest on the shot
const ZOOM_EASE = 0.22;        // fraction of the remaining distance covered per frame
const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform);

const el = (tag, cls, text) => {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
};

export function timeAgo(ts) {
  const s = Math.max(0, (Date.now() - ts) / 1000);
  if (s < 45) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

export class BoardView {
  /**
   * @param {HTMLElement} mount
   * @param {object} o { room, board, title, app, emptyText, tour, fitNotes, dblclickExpands }
   *   fitNotes: open zoomed so all notes just fit, centred on them (paper boards)
   *   dblclickExpands: double-click opens the board full screen instead of starting a note
   */
  constructor(mount, o) {
    Object.assign(this, { room: o.room, board: o.board, title: o.title, app: o.app });
    this.tourEnabled = !!o.tour && !matchMedia('(prefers-reduced-motion: reduce)').matches;
    this.fitNotes = !!o.fitNotes;
    this.dblclickExpands = !!o.dblclickExpands;
    this.scale = 1;          // current rendered scale
    this.base = 1;           // the "100%" scale: the board's centre quarter fills the view
    this.minScale = 0.5;     // smallest scale (50%): the whole board exactly covers the view
    this.target = 1;         // scale the zoom animation is heading to
    this.anchor = null;      // {cx, cy, px, py}: content point that stays under the cursor
    this.els = new Map();          // top-level note id -> element
    this.dragging = null;

    this.frame = el('div', 'pc-board-frame');
    this.titleBar = el('div', 'pc-fullscreen-title');
    this.titleBar.append(el('div', 'pc-fullscreen-name', o.title || ''));
    if (o.dblclickExpands) this.titleBar.append(el('div', 'pc-fullscreen-hint', 'Double click to leave a note'));
    this.titleBar.hidden = true;
    this.scroller = el('div', 'pc-board-scroll');
    this.sizer = el('div', 'pc-board-sizer');
    this.surface = el('div', 'pc-board-surface');
    this.empty = el('div', 'pc-board-empty', o.emptyText || 'Double-click anywhere to leave the first note');
    this.tools = el('div', 'pc-board-tools');
    this.fsButton = el('button', 'pc-btn pc-btn-sm pc-fs-btn', '⤢ Expand');
    this.fsButton.type = 'button';
    this.fsButton.addEventListener('click', () => this.toggleFullscreen());
    const tool = (label, title, fn) => {
      const b = el('button', 'pc-btn pc-btn-sm pc-zoom-btn', label);
      b.type = 'button'; b.title = title; b.setAttribute('aria-label', title);
      b.addEventListener('click', fn);
      return b;
    };
    this.zoomLabel = tool('100%', 'Show all notes', () => this.resetView());
    this.tools.append(
      tool('−', 'Zoom out', () => this.zoomTo(this.target / 1.4)),
      this.zoomLabel,
      tool('+', 'Zoom in', () => this.zoomTo(this.target * 1.4)),
      this.fsButton,
    );
    this.hint = el('div', 'pc-zoom-hint', `${IS_MAC ? '⌘' : 'Ctrl'} + scroll to zoom`);
    this.frame.append(this.hint);
    this.surface.append(this.empty);
    this.scroller.append(this.sizer, this.surface);
    this.frame.append(this.titleBar, this.tools, this.scroller);
    mount.append(this.frame);

    this.surface.addEventListener('dblclick', e => {
      if (e.target !== this.surface && e.target !== this.empty) return;
      // Small embedded boards expand on double-click; once expanded, double-click starts a note.
      if (this.dblclickExpands && !this.frame.classList.contains('is-fullscreen')) { this.toggleFullscreen(); return; }
      const r = this.surface.getBoundingClientRect();
      this.compose((e.clientX - r.left) / this.scale - NOTE_W / 2, (e.clientY - r.top) / this.scale - 20);
    });

    this.scroller.addEventListener('wheel', e => this.onWheel(e), { passive: false });
    this.surface.addEventListener('pointerdown', e => this.startPan(e));
    // Any hands-on contact with the board ends the intro tour for good.
    for (const type of ['pointerdown', 'touchstart', 'keydown']) {
      this.frame.addEventListener(type, () => this.stopTour(), { capture: true, passive: true });
    }
    this.visible = true;
    this.visibility = new IntersectionObserver(([entry]) => { this.visible = entry.isIntersecting; });
    this.visibility.observe(this.frame);

    this.resizeObserver = new ResizeObserver(() => this.layout());
    this.resizeObserver.observe(this.scroller);
    this.unsubscribe = this.room.subscribe(ev => this.onRoom(ev));
    this.onKey = e => { if (e.key === 'Escape' && this.frame.classList.contains('is-fullscreen')) this.toggleFullscreen(); };
    document.addEventListener('keydown', this.onKey);
    this.renderAll();
    this.layout(true);
  }

  get W() { return this.room.limits.boardW; }
  get H() { return this.room.limits.boardH; }

  // Width is read from the border box (scrollbar-independent) and only a real size change
  // re-fits. The viewport height depends only on that width, never on the zoom, so a scrollbar
  // appearing can't feed back into the layout (that loop is what made boards jitter).
  // Embedded, the viewport has the board's own aspect ratio, so fully zoomed out the board is
  // exactly the viewport: no dead margin, every visible spot can take a note. Fullscreen uses
  // "cover" for the same reason and pans along the longer side.
  layout(force = false) {
    const full = this.frame.classList.contains('is-fullscreen');
    const rect = this.scroller.getBoundingClientRect();
    const width = Math.floor(rect.width), height = Math.floor(rect.height);
    const key = full ? `${width}x${height}` : String(width);
    if (!force && key === this.lastKey) return;
    this.lastKey = key;
    const fit = full ? Math.max(width / this.W, height / this.H) : width / this.W;
    const first = !this.everLaidOut;
    const zoomed = first ? 1 : this.scale / this.base;   // keep the user's zoom across resizes
    const centre = first ? null : this.camera();
    this.everLaidOut = true;
    // 50% = the whole board exactly covers the viewport; 100% = twice that, the centre quarter.
    this.minScale = Math.ceil(fit * 10000) / 10000;   // round up: never leave a sub-pixel gap
    this.base = this.minScale * 2;
    if (!full) this.scroller.style.height = Math.floor(this.H * width / this.W) + 'px';
    cancelAnimationFrame(this.raf);
    this.raf = 0;
    this.anchor = null;
    this.target = this.clampScale(this.base * zoomed);
    // Open on the centre of the board; on later resizes keep looking at the same spot.
    this.setCamera({ s: this.target, cx: centre ? centre.cx : this.W / 2, cy: centre ? centre.cy : this.H / 2 });
    if (this.tourRaf) this.tourSegment(this.camera());   // re-plan the glide for the new viewport
  }

  clampScale(v) { return Math.min(Math.max(MAX_SCALE, this.base), Math.max(this.minScale, v)); }

  /** The middle zoom button: glide back to the default view (all notes in view). */
  resetView() {
    this.stopTour();
    cancelAnimationFrame(this.raf);
    this.raf = 0;
    const from = this.camera(), to = this.fitCamera();
    const t0 = performance.now(), ms = 450;
    const ease = t => 1 - (1 - t) ** 3;
    const step = now => {
      const k = ease(Math.min(1, (now - t0) / ms));
      this.setCamera({
        s: Math.exp(Math.log(from.s) + (Math.log(to.s) - Math.log(from.s)) * k),
        cx: from.cx + (to.cx - from.cx) * k,
        cy: from.cy + (to.cy - from.cy) * k,
      });
      if (k < 1) this.raf = requestAnimationFrame(step); else this.raf = 0;
    };
    this.raf = requestAnimationFrame(step);
  }

  applyScale(scale) {
    this.scale = scale;
    this.surface.style.width = this.W + 'px';
    this.surface.style.height = this.H + 'px';
    this.surface.style.transform = `scale(${scale})`;
    this.sizer.style.width = Math.floor(this.W * scale) + 'px';
    this.sizer.style.height = Math.floor(this.H * scale) + 'px';
    if (this.anchor) {
      const a = this.anchor;
      this.scroller.scrollLeft = a.cx * scale - a.px;
      this.scroller.scrollTop = a.cy * scale - a.py;
    }
    this.zoomLabel.textContent = Math.round((scale / this.base) * 100) + '%';
  }

  /** Smoothly zoom to `scale`, keeping the content under viewport point (px, py) fixed. */
  zoomTo(scale, px, py) {
    if (px === undefined) { px = this.scroller.clientWidth / 2; py = this.scroller.clientHeight / 2; }
    this.target = this.clampScale(scale);
    this.anchor = { cx: (this.scroller.scrollLeft + px) / this.scale, cy: (this.scroller.scrollTop + py) / this.scale, px, py };
    if (this.raf) return;
    this.surface.style.willChange = 'transform';
    const step = () => {
      const diff = this.target - this.scale;
      if (Math.abs(diff) < this.target * 0.002) {
        this.applyScale(this.target);
        this.raf = 0;
        this.anchor = null;
        // Drop the compositor layer once settled so text re-rasterises crisply at the new size.
        this.surface.style.willChange = '';
        return;
      }
      this.applyScale(this.scale + diff * ZOOM_EASE);
      this.raf = requestAnimationFrame(step);
    };
    this.raf = requestAnimationFrame(step);
  }

  onWheel(e) {
    const full = this.frame.classList.contains('is-fullscreen');
    // Embedded boards leave plain scrolling to the page; trackpad pinch (ctrlKey) and Ctrl/⌘
    // + wheel zoom. Fullscreen boards zoom on any wheel, like Miro.
    if (!full && !e.ctrlKey && !e.metaKey) { this.showHint(); return; }
    e.preventDefault();
    this.stopTour();
    const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1;
    const dy = Math.max(-120, Math.min(120, e.deltaY * unit));
    const r = this.scroller.getBoundingClientRect();
    this.zoomTo(this.target * Math.exp(-dy * 0.0025), e.clientX - r.left, e.clientY - r.top);
  }

  showHint() {
    const now = performance.now();
    if (now - (this.hintAt || 0) < 4000) return;
    this.hintAt = now;
    this.hint.classList.add('is-visible');
    clearTimeout(this.hintTimer);
    this.hintTimer = setTimeout(() => this.hint.classList.remove('is-visible'), 1400);
  }

  // ---------- intro tour ----------
  /** Camera = scale plus the board point at the centre of the viewport. */
  camera() {
    const w = this.scroller.clientWidth, h = this.scroller.clientHeight;
    return { s: this.scale, cx: (this.scroller.scrollLeft + w / 2) / this.scale, cy: (this.scroller.scrollTop + h / 2) / this.scale };
  }

  /**
   * The board's default view: zoomed so every note just fits, centred on them, but never more
   * than FIT_MAX_ZOOM x the whole-board view. An empty board shows the whole board.
   */
  fitCamera() {
    const nodes = [...this.els.values()];
    if (!nodes.length) return { s: this.minScale, cx: this.W / 2, cy: this.H / 2 };
    const pad = 24;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const n of nodes) {
      const x = parseFloat(n.style.left) || 0, y = parseFloat(n.style.top) || 0;
      x0 = Math.min(x0, x); y0 = Math.min(y0, y);
      x1 = Math.max(x1, x + n.offsetWidth); y1 = Math.max(y1, y + n.offsetHeight);
    }
    const vw = this.scroller.clientWidth, vh = this.scroller.clientHeight;
    const s = this.clampScale(Math.min(vw / (x1 - x0 + 2 * pad), vh / (y1 - y0 + 2 * pad), this.minScale * FIT_MAX_ZOOM));
    return { s, cx: (x0 + x1) / 2, cy: (y0 + y1) / 2 };
  }

  fitToNotes() { this.setCamera(this.fitCamera()); }

  setCamera({ s, cx, cy }) {
    const w = this.scroller.clientWidth, h = this.scroller.clientHeight;
    this.anchor = { cx, cy, px: w / 2, py: h / 2 };
    this.applyScale(s);
    this.anchor = null;
    this.target = s;
  }

  /**
   * Intro tour order: start at a random note (fresh on every page load), then visit every
   * note once, always moving to the nearest one not yet shown so the camera glides short
   * distances. Once every note has been shown, the camera pulls back to the whole wall, then
   * a new round starts from a new random note. Notes posted mid-round join the current round.
   */
  nextShot() {
    const overview = { s: this.minScale, cx: this.W / 2, cy: this.H / 2 };
    const notes = [...this.room.notes.values()].filter(n => n.board === this.board && this.els.has(n.id));
    if (!notes.length) {
      // Empty wall: drift between random spots and the whole wall.
      this.shotIndex = (this.shotIndex || 0) + 1;
      if (this.shotIndex % 2 === 0) return overview;
      return { s: this.clampScale(this.base * 1.8), cx: this.W * (0.2 + Math.random() * 0.6), cy: this.H * (0.25 + Math.random() * 0.5) };
    }
    this.shown = this.shown || new Set();
    let pool = notes.filter(n => !this.shown.has(n.id));
    if (!pool.length) {
      // Round complete: show the whole wall, then start the next round.
      this.shown.clear();
      this.lastShown = null;
      return overview;
    }
    const centre = n => { const node = this.els.get(n.id); return { x: n.x + node.offsetWidth / 2, y: n.y + node.offsetHeight / 2 }; };
    let n;
    const from = this.lastShown && this.room.notes.get(this.lastShown);
    if (!from || !this.els.has(from.id)) {
      n = pool[Math.floor(Math.random() * pool.length)];
    } else {
      const c0 = centre(from);
      n = pool.reduce((best, cand) => {
        const c = centre(cand), d = (c.x - c0.x) ** 2 + (c.y - c0.y) ** 2;
        return d < best.d ? { n: cand, d } : best;
      }, { n: null, d: Infinity }).n;
    }
    this.shown.add(n.id);
    this.lastShown = n.id;
    return this.closeUp(n);
  }

  /** Close-up on one note: about three notes across, but never so close that it is cut off. */
  closeUp(n) {
    const node = this.els.get(n.id);
    const w = node.offsetWidth, h = node.offsetHeight;
    const vw = this.scroller.clientWidth, vh = this.scroller.clientHeight;
    const preferred = Math.max(this.base * 1.8, vw / (NOTE_W * 3.4));
    const fits = Math.min((vw * 0.82) / w, (vh * 0.82) / h);   // whole note plus a margin
    return { s: this.clampScale(Math.min(preferred, fits)), cx: n.x + w / 2, cy: n.y + h / 2 };
  }

  tourSegment(from) {
    this.tour = { from, to: this.nextShot(), t0: performance.now() };
  }

  startTour() {
    if (!this.tourEnabled || this.tourStopped || this.tourRaf) return;
    this.tourSegment(this.camera());
    let last = performance.now();
    const ease = t => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2);
    const tick = now => {
      // Freeze the clock while off-screen or after a background-tab gap.
      if (!this.visible || now - last > 120) this.tour.t0 += now - last;
      last = now;
      if (this.visible && !this.dragging) {
        const { from, to, t0 } = this.tour;
        const t = (now - t0) / TOUR_MOVE_MS;
        if (t < 1) {
          const k = ease(Math.max(0, t));
          this.surface.style.willChange = 'transform';
          this.setCamera({
            s: Math.exp(Math.log(from.s) + (Math.log(to.s) - Math.log(from.s)) * k),   // zoom feels even in log space
            cx: from.cx + (to.cx - from.cx) * k,
            cy: from.cy + (to.cy - from.cy) * k,
          });
        } else if (now - t0 < TOUR_MOVE_MS + TOUR_HOLD_MS) {
          if (this.surface.style.willChange) { this.setCamera(to); this.surface.style.willChange = ''; }   // crisp text while resting
        } else {
          this.tourSegment(this.camera());
        }
      }
      this.tourRaf = requestAnimationFrame(tick);
    };
    this.tourRaf = requestAnimationFrame(tick);
  }

  stopTour() {
    if (this.tourStopped) return;
    this.tourStopped = true;
    cancelAnimationFrame(this.tourRaf);
    this.tourRaf = 0;
    this.surface.style.willChange = '';
    this.target = this.scale;
  }

  /** Dragging empty board space pans the view once it is zoomed past the viewport. */
  startPan(e) {
    if (e.button !== 0 || (e.target !== this.surface && e.target !== this.empty)) return;
    const sc = this.scroller;
    if (sc.scrollWidth <= sc.clientWidth && sc.scrollHeight <= sc.clientHeight) return;
    const start = { x: e.clientX, y: e.clientY, left: sc.scrollLeft, top: sc.scrollTop };
    this.surface.setPointerCapture(e.pointerId);
    this.surface.classList.add('is-panning');
    const move = ev => { sc.scrollLeft = start.left - (ev.clientX - start.x); sc.scrollTop = start.top - (ev.clientY - start.y); };
    const end = () => {
      this.surface.removeEventListener('pointermove', move);
      this.surface.removeEventListener('pointerup', end);
      this.surface.removeEventListener('pointercancel', end);
      this.surface.classList.remove('is-panning');
    };
    this.surface.addEventListener('pointermove', move);
    this.surface.addEventListener('pointerup', end);
    this.surface.addEventListener('pointercancel', end);
  }

  toggleFullscreen() {
    const on = !this.frame.classList.contains('is-fullscreen');
    this.frame.classList.toggle('is-fullscreen', on);
    this.titleBar.hidden = !on;
    this.fsButton.textContent = on ? '⤡ Collapse' : '⤢ Expand';
    if (on) {
      this.scrim = el('div', 'pc-scrim');
      this.scrim.addEventListener('click', () => this.toggleFullscreen());
      document.body.append(this.scrim);
      document.body.style.overflow = 'hidden';
    } else {
      this.scrim?.remove();
      document.body.style.overflow = '';
    }
    this.layout(true);
    // Expanding or collapsing opens on the default view: all notes in sight.
    this.fitToNotes();
  }

  // ---------- room events ----------
  onRoom(ev) {
    if (ev.type === 'reset') {
      this.renderAll();
      this.layout(true);   // the server's hello carries this room's board size
      // Initial view only: reconnects and later notes never move the user's camera.
      if (this.fitNotes && !this.fitted) { this.fitted = true; this.fitToNotes(); }
      if (this.tourEnabled && !this.tourStopped) setTimeout(() => this.startTour(), 900);
      return;
    }
    if (ev.type === 'upsert') {
      const n = ev.note;
      if (n.board !== this.board) return;
      this.upsertNote(n, ev.fresh);
    } else if (ev.type === 'remove') {
      const n = ev.note;
      if (n.board !== this.board) return;
      this.els.get(n.id)?.remove();
      this.els.delete(n.id);
      this.updateEmpty();
    } else if (ev.type === 'error' && ev.id && this.els.has(ev.id) && this.dragging?.id !== ev.id) {
      // The server refused a change to this note (e.g. a drop over the rate limit): put it
      // back where the server has it, so the screen never shows a position nobody else sees.
      const n = this.room.notes.get(ev.id);
      if (n) this.upsertNote(n, false);
    } else if (ev.type === 'drag') {
      const node = this.els.get(ev.id);
      if (!node || this.dragging?.id === ev.id) return;
      node.classList.add('remote-drag');
      node.style.left = ev.x + 'px';
      node.style.top = ev.y + 'px';
      clearTimeout(node._dragTimer);
      node._dragTimer = setTimeout(() => node.classList.remove('remote-drag'), 1200);
    }
  }

  renderAll() {
    for (const node of this.els.values()) node.remove();
    this.els.clear();
    const notes = [...this.room.notes.values()].filter(n => n.board === this.board).sort((a, b) => a.z - b.z);
    for (const n of notes) this.upsertNote(n, false);
    this.updateEmpty();
  }

  updateEmpty() { this.empty.hidden = this.els.size > 0; }

  isMine(n) { return !!this.room.me && n.authorId === this.room.me.id; }
  canDelete(n) { return this.isMine(n) || !!this.room.me?.admin; }

  upsertNote(n, fresh) {
    let node = this.els.get(n.id);
    if (!node) {
      node = this.buildNote(n);
      this.els.set(n.id, node);
      this.surface.append(node);
      if (fresh) { node.classList.add('fresh'); setTimeout(() => node.classList.remove('fresh'), 400); }
    }
    node.dataset.color = n.color;
    node.style.zIndex = String(n.z || 1);
    const body = node.querySelector('.pc-note-body');
    body.textContent = n.text;
    this.fitNote(node, n);
    if (this.dragging?.id !== n.id) {
      node.classList.remove('remote-drag');
      // A widened note is kept inside the board instead of being clipped at its edge.
      node.style.left = Math.min(n.x, Math.max(0, this.W - node.offsetWidth)) + 'px';
      node.style.top = Math.min(n.y, Math.max(0, this.H - node.offsetHeight)) + 'px';
    }
    const author = node.querySelector('.pc-note-author');
    author.textContent = n.authorName;
    if (this.isMine(n)) author.append(el('span', 'mine', ' (you)'));
    const time = node.querySelector('.pc-note-time');
    time.dataset.ts = n.created;
    time.textContent = timeAgo(n.created) + (n.updated - n.created > 1000 ? ' · edited' : '');
    node.title = n.movedBy ? `Last moved by ${n.movedBy}` : '';
    node.querySelector('[data-act=edit]').hidden = !this.isMine(n);
    node.querySelector('[data-act=delete]').hidden = !this.canDelete(n);
    this.updateEmpty();
  }

  /**
   * Notes never get taller than they are wide. A note that would at the default width is
   * widened until height / width hits a per-note ratio in [0.5, 1), chosen from its id so
   * the wall looks varied but every viewer sees the same shape.
   */
  fitNote(node, n) {
    if (node._fitText === n.text) return;
    node.style.width = NOTE_W + 'px';
    if (!node.offsetHeight) return;              // not laid out yet; retried on the next upsert
    node._fitText = n.text;
    if (node.offsetHeight <= NOTE_W) return;
    const lowest = NOTE_RATIO_MIN + NOTE_RATIO_SLACK;
    const ratio = lowest + (1 - lowest) * idFraction(n.id);
    let lo = NOTE_W, hi = NOTE_W_MAX;              // height/width falls as width grows
    for (let i = 0; i < 9; i++) {
      const mid = (lo + hi) / 2;
      node.style.width = mid + 'px';
      if (node.offsetHeight / mid > ratio) lo = mid; else hi = mid;
    }
    node.style.width = Math.ceil(hi) + 'px';
  }

  buildNote(n) {
    const node = el('article', 'pc-note');
    node.dataset.id = n.id;
    const body = el('div', 'pc-note-body');
    const foot = el('div', 'pc-note-foot');
    const actions = el('div', 'pc-note-actions');
    const btn = (act, label, title) => { const b = el('button', 'pc-icon-btn', label); b.type = 'button'; b.dataset.act = act; b.title = title; b.setAttribute('aria-label', title); return b; };
    actions.append(btn('edit', '✎', 'Edit your note'), btn('delete', '🗑', 'Delete'));
    foot.append(el('span', 'pc-note-author'), el('span', 'pc-note-time'), actions);

    node.append(body, foot);

    actions.addEventListener('click', e => {
      const act = e.target.closest('button')?.dataset.act;
      const note = this.room.notes.get(n.id);
      if (!act || !note) return;
      if (act === 'edit') this.editNote(note);
      else if (act === 'delete') this.deleteNote(note);
    });
    for (const target of [body, foot]) target.addEventListener('pointerdown', e => this.startDrag(e, n.id));
    node.addEventListener('dblclick', e => e.stopPropagation());
    return node;
  }

  // ---------- actions ----------
  /** New note at the centre of what the user is looking at, unless a point is given. */
  async compose(x, y) {
    this.stopTour();
    if (!this.app.requireLogin('post a note')) return;
    if (x === undefined) {
      const s = this.scale;
      x = (this.scroller.scrollLeft + this.scroller.clientWidth / 2) / s - NOTE_W / 2 + (Math.random() - 0.5) * 120;
      y = (this.scroller.scrollTop + Math.min(this.scroller.clientHeight, window.innerHeight) / 2) / s - 70 + (Math.random() - 0.5) * 80;
    }
    const result = await this.app.composer.open({ heading: 'New note', where: this.title, max: this.room.limits.textMax });
    if (!result) return;
    x = Math.min(Math.max(0, x), this.W - NOTE_W);
    y = Math.min(Math.max(0, y), this.H - 160);
    this.room.send({ t: 'create', board: this.board, text: result.text, color: result.color, x, y });
  }

  async editNote(note) {
    if (!note || !this.isMine(note)) return;
    const result = await this.app.composer.open({
      heading: 'Edit note', where: this.title, text: note.text, color: note.color,
      max: this.room.limits.textMax, submit: 'Save',
    });
    if (!result) return;
    this.room.send({ t: 'edit', id: note.id, text: result.text, color: result.color });
  }

  deleteNote(note) {
    if (!note) return;
    const own = this.isMine(note);
    if (!confirm(own ? 'Delete your note?' : `Remove this note by ${note.authorName}? (moderator)`)) return;
    this.room.send({ t: 'delete', id: note.id });
  }

  startDrag(e, id) {
    if (e.button !== 0 || this.dragging || e.target.closest('button, a')) return;
    const note = this.room.notes.get(id);
    const node = this.els.get(id);
    if (!note || !node) return;
    if (!this.app.user) { this.app.requireLogin('move notes'); return; }
    e.preventDefault();
    node.setPointerCapture(e.pointerId);
    const d = { id, node, startX: e.clientX, startY: e.clientY, x0: note.x, y0: note.y, x: note.x, y: note.y, lastSent: 0, moved: false };
    this.dragging = d;
    node.classList.add('dragging');
    node.style.zIndex = '99999';
    const maxX = Math.max(0, this.W - node.offsetWidth), maxY = Math.max(0, this.H - node.offsetHeight);
    const move = ev => {
      d.x = Math.round(Math.min(maxX, Math.max(0, d.x0 + (ev.clientX - d.startX) / this.scale)));
      d.y = Math.round(Math.min(maxY, Math.max(0, d.y0 + (ev.clientY - d.startY) / this.scale)));
      d.moved ||= Math.abs(d.x - d.x0) + Math.abs(d.y - d.y0) > 2;
      node.style.left = d.x + 'px';
      node.style.top = d.y + 'px';
      const now = performance.now();
      if (d.moved && now - d.lastSent > DRAG_SEND_MS) { d.lastSent = now; this.room.raw({ t: 'drag', id, x: d.x, y: d.y }); }
    };
    const end = () => {
      node.removeEventListener('pointermove', move);
      node.removeEventListener('pointerup', end);
      node.removeEventListener('pointercancel', end);
      node.classList.remove('dragging');
      this.dragging = null;
      if (d.moved && this.room.send({ t: 'move', id, x: d.x, y: d.y })) return; // server echo sets final z/pos
      const cur = this.room.notes.get(id);
      if (cur) this.upsertNote(cur, false);
    };
    node.addEventListener('pointermove', move);
    node.addEventListener('pointerup', end);
    node.addEventListener('pointercancel', end);
  }

  destroy() {
    if (this.frame.classList.contains('is-fullscreen')) this.toggleFullscreen();
    cancelAnimationFrame(this.raf);
    this.stopTour();
    this.visibility.disconnect();
    this.unsubscribe();
    this.resizeObserver.disconnect();
    document.removeEventListener('keydown', this.onKey);
    this.frame.remove();
  }
}
