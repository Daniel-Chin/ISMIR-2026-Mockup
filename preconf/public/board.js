// A scalable corkboard bound to one board id inside a Room.
// All user text goes through textContent; nothing from the server is parsed as HTML.

export const NOTE_W = 230;     // default width; short notes keep it
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
export const MAX_SCALE = 3;    // absolute: notes at 3x their logical size
// The fitted "all notes" view zooms in no closer than 200%: a lone note should not blow up
// to fill the screen. (100% = the base board fills the view; see BOARD_EXPAND on the server.)
const FIT_MAX_PERCENT = 200;
const TOUR_MOVE_MS = 4500;     // intro camera: one glide between shots
const TOUR_HOLD_MS = 2200;     // ...then rest on the shot
const ZOOM_EASE = 0.22;        // fraction of the remaining distance covered per frame
// Notes of up to this many wrapped lines can't be taller than wide: no need to measure them.
const SHORT_NOTE_LINES = 7, CHARS_PER_LINE = 24;

export const el = (tag, cls, text) => {
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
   * @param {object} o { room, board, title, app, emptyText, tour, fitNotes, dblclickExpands, createExtras }
   *   fitNotes: open zoomed so all notes just fit, centred on them (paper boards)
   *   dblclickExpands: double-click opens the board full screen instead of starting a note
   *   createExtras: () => extra fields for a new note (its place on the Paper Wall)
   *   noteTag: note => short label of what the note is about (a paper id), shown by its author
   *
   * Subclasses (the Paper Wall, wall.js) override owns / notePos / sendMove / isPanTarget.
   * They run during this constructor, so they may only read `this.opts`.
   */
  constructor(mount, o) {
    this.opts = o;
    Object.assign(this, { room: o.room, board: o.board, title: o.title, app: o.app });
    this.tourEnabled = !!o.tour && !matchMedia('(prefers-reduced-motion: reduce)').matches;
    this.fitNotes = !!o.fitNotes;
    this.dblclickExpands = !!o.dblclickExpands;
    this.scale = 1;          // current rendered scale
    this.base = 1;           // the "100%" scale: the base board (the centre 1/expand) fills the view
    this.minScale = 0.25;    // smallest scale (100/expand %): the whole board exactly covers the view
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
    this.surface.append(this.empty);
    this.scroller.append(this.sizer, this.surface);
    this.frame.append(this.titleBar, this.tools, this.scroller);
    mount.append(this.frame);

    this.surface.addEventListener('dblclick', e => {
      if (!this.isPanTarget(e.target)) return;
      // Small embedded boards expand on double-click; once expanded, double-click starts a note.
      if (this.dblclickExpands && !this.frame.classList.contains('is-fullscreen')) { this.expandAt(e); return; }
      const r = this.surface.getBoundingClientRect();
      this.compose((e.clientX - r.left) / this.scale - NOTE_W / 2, (e.clientY - r.top) / this.scale - 20);
    });

    this.scroller.addEventListener('wheel', e => this.onWheel(e), { passive: false });
    // Two fingers on a board zoom (and pan) the board, never the page around it.
    this.scroller.addEventListener('touchstart', e => this.onTouch(e), { passive: false });
    this.scroller.addEventListener('touchmove', e => this.onTouch(e), { passive: false });
    this.scroller.addEventListener('touchend', e => this.onTouch(e));
    this.scroller.addEventListener('touchcancel', e => this.onTouch(e));
    // Safari reports pinches (iPad, Mac trackpad) as gesture events; without these it zooms the page.
    for (const type of ['gesturestart', 'gesturechange', 'gestureend']) {
      this.scroller.addEventListener(type, e => this.onGesture(e), { passive: false });
    }
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
    // The room may already be live (the hall reuses the wall's connections): no 'reset' will
    // come, so open on the default view now.
    if (this.room.ready && this.fitNotes) { this.fitted = true; this.fitToNotes(); }
  }

  get W() { return this.room.limits.boardW; }
  get H() { return this.room.limits.boardH; }

  // ---------- hooks (overridden by the Paper Wall) ----------
  /** Does this view show note `n`? */
  owns(n) { return n.board === this.board; }
  /** Where note `n` sits on this surface. */
  notePos(n) { return { x: n.x, y: n.y }; }
  /** Send a drag preview (final=false) or the drop (final=true); returns false when offline. */
  sendMove(final, id, x, y) { return final ? this.room.send({ t: 'move', id, x, y }) : this.room.raw({ t: 'drag', id, x, y }); }
  /** Can a press on `target` pan the board (and a double-click start a note)? */
  isPanTarget(target) { return target === this.surface || target === this.empty; }

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
    if (!width) return;   // hidden (e.g. the wall while the hall is shown): nothing to fit to
    const key = full ? `${width}x${height}` : String(width);
    if (!force && key === this.lastKey) return;
    this.lastKey = key;
    const fit = this.fitScale(width, height, full);
    const first = !this.everLaidOut;
    const zoomed = first ? 1 : this.scale / this.base;   // keep the user's zoom across resizes
    const centre = first ? null : this.camera();
    this.everLaidOut = true;
    // 50% = the whole board exactly covers the viewport; 100% = twice that, the centre quarter.
    this.minScale = Math.ceil(fit * 10000) / 10000;   // round up: never leave a sub-pixel gap
    // The server says how many times the base board each board is (BOARD_EXPAND).
    this.base = this.minScale * (Number(this.room.limits.expand) || 2);
    if (!full) this.scroller.style.height = Math.floor(this.H * width / this.W) + 'px';
    cancelAnimationFrame(this.raf);
    this.raf = 0;
    this.anchor = null;
    this.setMoving(false);
    this.target = this.clampScale(this.base * zoomed);
    // Open on the centre of the board; on later resizes keep looking at the same spot.
    this.setCamera({ s: this.target, cx: centre ? centre.cx : this.W / 2, cy: centre ? centre.cy : this.H / 2 });
    if (this.tourRaf) this.tourSegment(this.camera());   // re-plan the glide for the new viewport
  }

  /**
   * The smallest zoom. Embedded, the frame has the board's shape: the board fills its width.
   * Expanded, the frame is the whole window, whatever its shape: the board covers it, so every
   * spot can take a note (the wall overrides this to show all of itself).
   */
  fitScale(width, height, full) { return full ? Math.max(width / this.W, height / this.H) : width / this.W; }

  clampScale(v) { return Math.min(Math.max(MAX_SCALE, this.base), Math.max(this.minScale, v)); }

  /** The middle zoom button: glide back to the default view (all notes in view). */
  resetView() { this.glideTo(this.fitCamera()); }

  /** Glide the camera to `to` ({s, cx, cy}). */
  glideTo(to) {
    this.stopTour();
    cancelAnimationFrame(this.raf);
    this.raf = 0;
    const from = this.camera();
    to = this.reachable(to);
    const t0 = performance.now(), ms = 450;
    const ease = t => 1 - (1 - t) ** 3;
    // A zoom glides about the one board point that sits at the same screen spot in both views,
    // so the picture only ever grows or shrinks towards its goal; panning the centre in a
    // straight line while zooming would first drift the wrong way (and then snap back).
    const zooming = Math.abs(Math.log(to.s / from.s)) > 0.05;
    const pivot = (a, b) => (a * from.s - b * to.s) / (from.s - to.s);
    const px = zooming ? pivot(from.cx, to.cx) : 0, py = zooming ? pivot(from.cy, to.cy) : 0;
    this.setMoving(true, to.s > from.s * 1.001);
    const step = now => {
      // rAF's timestamp is the frame's start, which can be a moment before t0: never run backwards.
      const k = ease(Math.min(1, Math.max(0, (now - t0) / ms)));
      const s = Math.exp(Math.log(from.s) + (Math.log(to.s) - Math.log(from.s)) * k);
      this.setCamera(zooming
        ? { s, cx: px - (px - from.cx) * from.s / s, cy: py - (py - from.cy) * from.s / s }
        : { s, cx: from.cx + (to.cx - from.cx) * k, cy: from.cy + (to.cy - from.cy) * k });
      if (k < 1) this.raf = requestAnimationFrame(step); else { this.raf = 0; this.setMoving(false); }
    };
    this.raf = requestAnimationFrame(step);
  }

  /** The camera closest to `to` that the board can show: near an edge, the view stops at it. */
  reachable(to) {
    const s = this.clampScale(to.s);
    const half = (view, size, c) => {
      const h = view / 2 / s;
      return size * s <= view ? size / 2 : Math.min(Math.max(c, h), size - h);
    };
    return { s, cx: half(this.scroller.clientWidth, this.W, to.cx), cy: half(this.scroller.clientHeight, this.H, to.cy) };
  }

  applyScale(scale) {
    this.scale = scale;
    // Zoomed out past the viewport (the expanded wall shows all of itself on any screen shape):
    // centre the board, with plain board background around it.
    this.offX = Math.max(0, (this.scroller.clientWidth - this.W * scale) / 2);
    this.offY = Math.max(0, (this.scroller.clientHeight - this.H * scale) / 2);
    this.surface.style.left = this.offX + 'px';
    this.surface.style.top = this.offY + 'px';
    this.surface.style.width = this.W + 'px';
    this.surface.style.height = this.H + 'px';
    this.surface.style.transform = `scale(${scale})`;
    this.sizer.style.width = Math.floor(this.W * scale) + 'px';
    this.sizer.style.height = Math.floor(this.H * scale) + 'px';
    if (this.anchor) {
      const a = this.anchor;
      this.scroller.scrollLeft = a.cx * scale + this.offX - a.px;
      this.scroller.scrollTop = a.cy * scale + this.offY - a.py;
    }
    this.zoomLabel.textContent = Math.round((scale / this.base) * 100) + '%';
  }

  /**
   * A zoom/glide/pinch starts or stops. Zooming IN, the board becomes one compositor layer that
   * is only scaled (cheap, and everything it needs is already drawn); when it stops the layer is
   * dropped so text re-renders crisply. Zooming OUT it stays an ordinary layer drawn every frame:
   * a scaled layer would show the parts coming into view as blank until drawn, which flickers.
   */
  setMoving(on, layer = false) {
    this.moving = on;
    const want = on && layer ? 'transform' : '';
    if (this.surface.style.willChange !== want) this.surface.style.willChange = want;
  }

  /** The motion turned into a zoom out: leave the scaled layer (see setMoving). */
  dropLayerIfZoomingOut(next) {
    if (next < this.scale && this.surface.style.willChange) this.surface.style.willChange = '';
  }

  /** Smoothly zoom to `scale`, keeping the content under viewport point (px, py) fixed. */
  zoomTo(scale, px, py) {
    if (px === undefined) { px = this.scroller.clientWidth / 2; py = this.scroller.clientHeight / 2; }
    this.target = this.clampScale(scale);
    this.anchor = { cx: (this.scroller.scrollLeft + px - (this.offX || 0)) / this.scale, cy: (this.scroller.scrollTop + py - (this.offY || 0)) / this.scale, px, py };
    if (this.raf) { this.dropLayerIfZoomingOut(this.target); return; }
    this.setMoving(true, this.target > this.scale);
    const step = () => {
      const diff = this.target - this.scale;
      if (Math.abs(diff) < this.target * 0.002) {
        this.applyScale(this.target);
        this.raf = 0;
        this.anchor = null;
        this.setMoving(false);
        return;
      }
      this.applyScale(this.scale + diff * ZOOM_EASE);
      this.raf = requestAnimationFrame(step);
    };
    this.raf = requestAnimationFrame(step);
  }

  /** Two-finger pinch on a touch screen: the board point between the fingers stays between them. */
  onTouch(e) {
    if (e.touches.length !== 2) {
      if (this.pinch && e.touches.length < 2) {
        cancelAnimationFrame(this.pinch.raf);
        const last = this.pinch.next;
        if (last) { this.anchor = { cx: this.pinch.cx, cy: this.pinch.cy, px: last.px, py: last.py }; this.applyScale(last.s); this.anchor = null; this.target = last.s; }
        this.pinch = null;
        this.setMoving(false);   // settle: text re-renders crisply
      }
      return;
    }
    e.preventDefault();
    const [a, b] = e.touches;
    const r = this.scroller.getBoundingClientRect();
    const dist = Math.hypot(a.clientX - b.clientX, a.clientY - b.clientY) || 1;
    const px = (a.clientX + b.clientX) / 2 - r.left, py = (a.clientY + b.clientY) / 2 - r.top;
    if (!this.pinch || e.type === 'touchstart') {
      this.stopTour();
      cancelAnimationFrame(this.raf);
      this.raf = 0;
      this.pinch = { dist, s: this.scale, cx: (this.scroller.scrollLeft + px - (this.offX || 0)) / this.scale, cy: (this.scroller.scrollTop + py - (this.offY || 0)) / this.scale };
      return;
    }
    // Touch events can outpace the screen: keep the latest and draw once per frame.
    this.pinch.next = { s: this.clampScale(this.pinch.s * dist / this.pinch.dist), px, py };
    if (this.pinch.raf) return;
    if (!this.moving) this.setMoving(true, this.pinch.next.s > this.scale);
    this.pinch.raf = requestAnimationFrame(() => {
      const p = this.pinch;
      if (!p) return;
      p.raf = 0;
      this.dropLayerIfZoomingOut(p.next.s);
      this.anchor = { cx: p.cx, cy: p.cy, px: p.next.px, py: p.next.py };
      this.applyScale(p.next.s);
      this.anchor = null;
      this.target = p.next.s;
    });
  }

  /** Safari's pinch (gesturestart/change/end, e.scale relative to the start). */
  onGesture(e) {
    e.preventDefault();
    if (this.pinch) return;   // a touch pinch already handles it (iPad sends both)
    if (e.type === 'gesturestart') { this.stopTour(); this.gesture = { s: this.target }; return; }
    if (e.type === 'gestureend') { this.gesture = null; return; }
    if (!this.gesture) return;
    const r = this.scroller.getBoundingClientRect();
    this.zoomTo(this.gesture.s * e.scale, e.clientX - r.left, e.clientY - r.top);
  }

  onWheel(e) {
    // Safari may also send ctrl+wheel for the pinch it reports as a gesture: zoom once.
    if (this.gesture && e.ctrlKey) { e.preventDefault(); return; }
    // The wheel over a board zooms it, about the pointer, embedded or expanded alike; it never
    // scrolls the board (drag empty space to move around) nor the page behind it.
    e.preventDefault();
    this.stopTour();
    const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1;
    const dy = Math.max(-120, Math.min(120, e.deltaY * unit));
    const r = this.scroller.getBoundingClientRect();
    this.zoomTo(this.target * Math.exp(-dy * 0.0025), e.clientX - r.left, e.clientY - r.top);
  }

  // ---------- intro tour ----------
  /** Camera = scale plus the board point at the centre of the viewport. */
  camera() {
    const w = this.scroller.clientWidth, h = this.scroller.clientHeight;
    return { s: this.scale, cx: (this.scroller.scrollLeft + w / 2 - (this.offX || 0)) / this.scale, cy: (this.scroller.scrollTop + h / 2 - (this.offY || 0)) / this.scale };
  }

  /**
   * The board's default view: zoomed so every note just fits, centred on them, but never more
   * than FIT_MAX_PERCENT %. An empty board shows 100%, centred, so its
   * "no notes yet" hint (centred on the board) sits in the middle of the view.
   */
  fitCamera() {
    const nodes = [...this.els.values()];
    if (!nodes.length) return { s: this.base, cx: this.W / 2, cy: this.H / 2 };
    const pad = 24;
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const n of nodes) {
      const x = parseFloat(n.style.left) || 0, y = parseFloat(n.style.top) || 0;
      x0 = Math.min(x0, x); y0 = Math.min(y0, y);
      x1 = Math.max(x1, x + n.offsetWidth); y1 = Math.max(y1, y + n.offsetHeight);
    }
    const vw = this.scroller.clientWidth, vh = this.scroller.clientHeight;
    const s = this.clampScale(Math.min(vw / (x1 - x0 + 2 * pad), vh / (y1 - y0 + 2 * pad), this.base * FIT_MAX_PERCENT / 100));
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
   * distances. Once every note has been shown, the camera pulls back to the default view, then
   * a new round starts from a new random note. Notes posted mid-round join the current round.
   */
  nextShot() {
    // "Overview" = the board's default view (all notes just in view, at most 200%; see fitCamera).
    const overview = this.fitCamera();
    const notes = [...this.room.notes.values()].filter(n => this.owns(n) && this.els.has(n.id));
    if (!notes.length) {
      // Empty wall: drift between random spots and the default view.
      this.shotIndex = (this.shotIndex || 0) + 1;
      if (this.shotIndex % 2 === 0) return overview;
      return { s: this.clampScale(this.base * 1.8), cx: this.W * (0.2 + Math.random() * 0.6), cy: this.H * (0.25 + Math.random() * 0.5) };
    }
    this.shown = this.shown || new Set();
    let pool = notes.filter(n => !this.shown.has(n.id));
    if (!pool.length) {
      // Round complete: back to the default view, then start the next round.
      this.shown.clear();
      this.lastShown = null;
      return overview;
    }
    const centre = n => { const node = this.els.get(n.id), p = this.notePos(n); return { x: p.x + node.offsetWidth / 2, y: p.y + node.offsetHeight / 2 }; };
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
    const p = this.notePos(n);
    return { s: this.clampScale(Math.min(preferred, fits)), cx: p.x + w / 2, cy: p.y + h / 2 };
  }

  tourSegment(from) {
    this.tour = { from, to: this.nextShot(), t0: performance.now() };
  }

  startTour() {
    if (!this.tourEnabled || this.tourStopped || this.tourRaf) return;
    // First "shot" is the default view we are already on: start it as finished, so the camera
    // rests for TOUR_HOLD_MS before gliding to the first note.
    const wall = this.fitCamera();
    this.setCamera(wall);
    this.tour = { from: wall, to: wall, t0: performance.now() - TOUR_MOVE_MS };
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
  /** `always`: pan even from a non-pan target (a note, for visitors who may not move it). */
  startPan(e, always = false) {
    if (e.button !== 0 || (!always && !this.isPanTarget(e.target))) return;
    // No text selection or native drag: a selection being dragged makes the browser auto-scroll
    // the board against the pan, and dragging selected text cancels the pan outright.
    e.preventDefault();
    window.getSelection?.()?.removeAllRanges();
    // A zoom or glide still running would keep moving the view under the hand: stop it here.
    cancelAnimationFrame(this.raf);
    this.raf = 0;
    this.anchor = null;
    this.target = this.scale;
    this.glide = null;   // the wall would otherwise resume an interrupted glide (wall.js)
    this.setMoving(false);
    const sc = this.scroller;
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

  /**
   * Double-click on an embedded board: expand it around the pointer. The board point under the
   * pointer stays under it and the zoom stays the same, so it feels like opening up that spot
   * (near an edge the view stops at the board's edge instead).
   */
  expandAt(e) {
    const r = this.surface.getBoundingClientRect();
    const at = { cx: (e.clientX - r.left) / this.scale, cy: (e.clientY - r.top) / this.scale, x: e.clientX, y: e.clientY };
    const s = this.scale;
    this.toggleFullscreen({ keepView: true });
    const v = this.scroller.getBoundingClientRect();
    this.anchor = { cx: at.cx, cy: at.cy, px: at.x - v.left, py: at.y - v.top };
    this.applyScale(this.clampScale(s));
    this.anchor = null;
    this.target = this.scale;
  }

  /**
   * Expand / Collapse keep what you are looking at: the same spot at the same zoom (expandAt
   * passes keepView and places the spot under the pointer itself). Collapsing returns the page
   * to exactly where it was.
   */
  toggleFullscreen({ keepView = false } = {}) {
    const on = !this.frame.classList.contains('is-fullscreen');
    const before = keepView ? null : this.camera();
    const mount = this.frame.parentElement;
    if (on) {
      // The expanded board floats above the page; its mount keeps the board's height so nothing
      // below moves up (which would leave the page somewhere else on collapse).
      this.pageY = window.scrollY;
      mount.style.minHeight = this.frame.getBoundingClientRect().height + 'px';
    }
    this.frame.classList.toggle('is-fullscreen', on);
    this.titleBar.hidden = !on;
    this.fsButton.textContent = on ? '⤡ Collapse' : '⤢ Expand';
    if (on) {
      this.scrim = el('div', 'pc-scrim');
      this.scrim.addEventListener('click', () => this.toggleFullscreen());
      document.body.append(this.scrim);
      // Lock the page behind (it scrolls on <html>): nothing done on the board may move it.
      document.documentElement.classList.add('pc-board-expanded');
    } else {
      this.scrim?.remove();
      document.documentElement.classList.remove('pc-board-expanded');
      mount.style.minHeight = '';
      if (this.pageY !== undefined) window.scrollTo({ top: this.pageY, behavior: 'instant' });
    }
    this.layout(true);
    if (before) this.setCamera(this.reachable(before));
  }

  /**
   * The part of the board that is actually on screen, in board units: an embedded board can be
   * partly scrolled out of the window. null when none of it is visible.
   */
  visibleRect() {
    const r = this.scroller.getBoundingClientRect();
    const left = Math.max(r.left, 0), right = Math.min(r.right, window.innerWidth);
    const top = Math.max(r.top, 0), bottom = Math.min(r.bottom, window.innerHeight);
    if (right - left < 20 || bottom - top < 20) return null;
    const s = this.scale, sl = this.scroller.scrollLeft - (this.offX || 0) - r.left, st = this.scroller.scrollTop - (this.offY || 0) - r.top;
    return {
      x0: Math.max(0, (sl + left) / s), x1: Math.min(this.W, (sl + right) / s),
      y0: Math.max(0, (st + top) / s), y1: Math.min(this.H, (st + bottom) / s),
    };
  }

  /** Bring a note you just posted fully into view (a short glide, same zoom) if it isn't. */
  revealNote(id) {
    const node = this.els.get(id), v = this.visibleRect();
    if (!node || !v) return;
    const x = parseFloat(node.style.left) || 0, y = parseFloat(node.style.top) || 0;
    const w = node._w || NOTE_W, h = node._h || 160, m = 16 / this.scale;
    const shift = (lo, size, v0, v1) => {
      if (size + 2 * m > v1 - v0) return lo + size / 2 - (v0 + v1) / 2;   // bigger than the view: centre it
      if (lo - m < v0) return lo - m - v0;
      if (lo + size + m > v1) return lo + size + m - v1;
      return 0;
    };
    const dx = shift(x, w, v.x0, v.x1), dy = shift(y, h, v.y0, v.y1);
    if (!dx && !dy) return;
    const c = this.camera();
    this.glideTo({ s: this.scale, cx: c.cx + dx, cy: c.cy + dy });
  }

  // ---------- room events ----------
  onRoom(ev) {
    if (ev.type === 'reset') {
      this.renderAll();
      this.layout(true);   // the server's hello carries this room's board size
      // Initial view only: reconnects and later notes never move the user's camera.
      if (this.fitNotes && !this.fitted) { this.fitted = true; this.fitToNotes(); }
      if (this.tourEnabled && !this.tourStopped && !this.tourRaf) {
        // The tour opens on the default view (all notes in sight) and rests there first.
        this.setCamera(this.fitCamera());
        setTimeout(() => this.startTour(), 900);
      }
      return;
    }
    if (ev.type === 'upsert') {
      const n = ev.note;
      if (!this.owns(n)) return;
      const node = ev.replaces && this.els.get(ev.replaces);
      if (node) { this.els.delete(ev.replaces); node.dataset.id = n.id; this.els.set(n.id, node); }
      this.upsertNote(n, ev.fresh);
      // Your own new note (shown before the server confirms it): make sure you can see it.
      if (ev.fresh && n.pending) this.revealNote(n.id);
    } else if (ev.type === 'remove') {
      const n = ev.note;
      if (!this.owns(n)) return;
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

  /** Bring the board in line with the room: update notes in place, add new ones, drop gone ones. */
  renderAll() {
    const keep = new Set();
    for (const n of this.room.notes.values()) {
      if (!this.owns(n)) continue;
      keep.add(n.id);
      this.upsertNote(n, false);
    }
    for (const [id, node] of this.els) if (!keep.has(id)) { node.remove(); this.els.delete(id); }
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
      // A widened note is kept inside the board instead of being clipped at its edge. Its size
      // comes from fitNote (no layout read per note: hundreds arrive at once on the wall).
      const p = this.notePos(n);
      node.style.left = Math.min(Math.max(0, p.x), Math.max(0, this.W - (node._w || NOTE_W))) + 'px';
      node.style.top = Math.min(Math.max(0, p.y), Math.max(0, this.H - (node._h || 160))) + 'px';
    }
    // Posted, not yet confirmed by the server: shown, but not editable or movable yet.
    node.classList.toggle('is-pending', !!n.pending);
    const author = node.querySelector('.pc-note-author');
    author.textContent = n.authorName;
    if (this.isMine(n)) author.append(el('span', 'mine', ' (you)'));
    // "[P1-01] · 1d ago": with a tag, the name gets the foot's first line; tag, time and
    // buttons the second.
    const tag = this.opts.noteTag?.(n) || '';
    const to = node.querySelector('.pc-note-to');
    to.textContent = tag ? `[${tag}] · ` : '';
    to.title = tag ? `Note on ${tag}` : '';
    to.hidden = !tag;
    node.querySelector('.pc-note-foot').classList.toggle('has-tag', !!tag);
    const time = node.querySelector('.pc-note-time');
    time.dataset.ts = n.created;
    time.textContent = timeAgo(n.created) + (n.updated - n.created > 1000 ? ' · edited' : '');
    node.title = n.movedBy ? `Last moved by ${n.movedBy}` : '';
    node.querySelector('[data-act=edit]').hidden = !!n.pending || !this.isMine(n);
    node.querySelector('[data-act=delete]').hidden = !!n.pending || !this.canDelete(n);
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
    // Most notes are short: count wrapped lines instead of asking the browser for a layout.
    const lines = String(n.text).split('\n').reduce((sum, line) => sum + Math.max(1, Math.ceil([...line].length / CHARS_PER_LINE)), 0);
    if (lines <= SHORT_NOTE_LINES) { node._fitText = n.text; node._w = NOTE_W; node._h = 56 + lines * 19; return; }
    if (!node.offsetHeight) return;              // not laid out yet; retried on the next upsert
    node._fitText = n.text;
    node._w = NOTE_W; node._h = node.offsetHeight;
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
    node._w = Math.ceil(hi); node._h = node.offsetHeight;
  }

  buildNote(n) {
    const node = el('article', 'pc-note');
    node.dataset.id = n.id;
    const body = el('div', 'pc-note-body');
    const foot = el('div', 'pc-note-foot');
    const actions = el('div', 'pc-note-actions');
    const btn = (act, label, title) => { const b = el('button', 'pc-icon-btn', label); b.type = 'button'; b.dataset.act = act; b.title = title; b.setAttribute('aria-label', title); return b; };
    actions.append(btn('edit', '✎', 'Edit your note'), btn('delete', '🗑', 'Delete'));
    foot.append(el('span', 'pc-note-author'), el('span', 'pc-note-to'), el('span', 'pc-note-time'), actions);

    node.append(body, foot);

    actions.addEventListener('click', e => {
      const act = e.target.closest('button')?.dataset.act;
      const note = this.room.notes.get(node.dataset.id);
      if (!act || !note) return;
      if (act === 'edit') this.editNote(note);
      else if (act === 'delete') this.deleteNote(note);
    });
    for (const target of [body, foot]) target.addEventListener('pointerdown', e => this.startDrag(e, node.dataset.id));
    node.addEventListener('dblclick', e => e.stopPropagation());
    return node;
  }

  // ---------- actions ----------
  /** New note at the centre of what the user is looking at, unless a point is given. */
  async compose(x, y) {
    this.stopTour();
    if (!this.app.requireLogin('post a note')) return;
    if (x === undefined) {
      // The middle of the part of the board you can see (not of the whole frame, which may be
      // partly scrolled off screen), nudged a little so notes posted in a row don't stack.
      const v = this.visibleRect() || { x0: 0, x1: this.W, y0: 0, y1: this.H };
      const jx = Math.min(60, (v.x1 - v.x0) / 6), jy = Math.min(40, (v.y1 - v.y0) / 6);
      x = (v.x0 + v.x1) / 2 - NOTE_W / 2 + (Math.random() - 0.5) * 2 * jx;
      y = (v.y0 + v.y1) / 2 - 70 + (Math.random() - 0.5) * 2 * jy;
    }
    const result = await this.app.composer.open({ heading: 'New note', where: this.title, max: this.room.limits.textMax });
    if (!result) return;
    x = Math.min(Math.max(0, x), this.W - NOTE_W);
    y = Math.min(Math.max(0, y), this.H - 160);
    this.room.send({ t: 'create', board: this.board, text: result.text, color: result.color, x, y, ...(this.opts.createExtras?.() || {}) });
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
    // Signed out: notes stay put and nobody is nagged; dragging one just moves the view.
    // A post not yet confirmed can't move either (the server doesn't know it yet).
    if (!this.app.user || note.pending) { this.startPan(e, true); return; }
    e.preventDefault();
    node.setPointerCapture(e.pointerId);
    // Start from where the note is drawn (it may have been nudged inside the board's edge).
    const x0 = parseFloat(node.style.left) || 0, y0 = parseFloat(node.style.top) || 0;
    const d = { id, node, startX: e.clientX, startY: e.clientY, x0, y0, x: x0, y: y0, lastSent: 0, moved: false };
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
      if (d.moved && now - d.lastSent > DRAG_SEND_MS) { d.lastSent = now; this.sendMove(false, id, d.x, d.y); }
    };
    const end = () => {
      node.removeEventListener('pointermove', move);
      node.removeEventListener('pointerup', end);
      node.removeEventListener('pointercancel', end);
      node.classList.remove('dragging');
      this.dragging = null;
      if (d.moved && this.sendMove(true, id, d.x, d.y)) return; // server echo sets final z/pos
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
