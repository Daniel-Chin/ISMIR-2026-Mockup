// One live connection per room ("welcome" or "session:PS-xx"). Keeps the note map from the
// server and fans events out to the board views that subscribe.
//
// What happens where:
//   - Zooming, panning, expanding: this browser only, never sent.
//   - Dragging a note: previews (~14/s) so others see it move; the drop is the one stored move.
//   - Posting, editing, deleting, dropping: shown here at once (optimistic), then confirmed by
//     the server's echo, or rolled back if the server refuses (rate limit, permissions, offline).

import { wsUrl, wsProtocols, serverClock } from './api.js';

const PING_MS = 30_000;

export class Room {
  constructor(name) {
    this.name = name;
    this.notes = new Map();
    this.me = null;
    this.limits = { boardW: 1600, boardH: 1000, textMax: 600 };
    this.status = 'connecting';
    this.ready = false;        // true once the first snapshot (hello) has arrived
    this.pending = new Map();  // cid -> temporary id of a note posted but not yet confirmed
    this.backup = new Map();   // note id -> its state before an optimistic change
    this.listeners = new Set();
    this.retry = 0;
    this.closed = false;
    this.connect();
  }

  subscribe(fn) { this.listeners.add(fn); return () => this.listeners.delete(fn); }
  emit(ev) { for (const fn of this.listeners) { try { fn(ev); } catch (e) { console.error(e); } } }

  connect() {
    if (this.closed) return;
    const ws = new WebSocket(wsUrl('/ws/' + this.name), wsProtocols());
    this.ws = ws;
    ws.onopen = () => {
      this.retry = 0;
      this.setStatus('live');
      clearInterval(this.pinger);
      this.pinger = setInterval(() => this.raw({ t: 'ping' }), PING_MS);
    };
    ws.onmessage = e => {
      let msg;
      try { msg = JSON.parse(e.data); } catch { return; }
      this.receive(msg);
    };
    ws.onclose = () => {
      clearInterval(this.pinger);
      if (this.closed) return;
      this.setStatus('offline');
      // Exponential backoff with jitter so 500 browsers don't reconnect in lockstep after a deploy.
      const wait = Math.min(15_000, 800 * 2 ** this.retry++) * (0.6 + Math.random() * 0.8);
      this.reconnectTimer = setTimeout(() => this.connect(), wait);
    };
    ws.onerror = () => { /* onclose follows */ };
  }

  setStatus(s) { this.status = s; this.emit({ type: 'status', status: s }); }

  /**
   * Notes fetched in one request with every other session's (app.js, /api/snapshot) while this
   * room's connection is still queued behind the others. The connection's own snapshot (hello)
   * replaces them when it arrives; until then the notes show but nothing can be sent.
   */
  seed(notes) {
    if (this.ready || !Array.isArray(notes)) return;
    this.notes = new Map(notes.map(n => [n.id, n]));
    this.ready = true;
    this.emit({ type: 'reset' });
  }

  receive(msg) {
    switch (msg.t) {
      case 'hello':
        this.notes = new Map(msg.notes.map(n => [n.id, n]));
        this.me = msg.me;
        if (msg.limits) this.limits = msg.limits;
        this.pending.clear();
        this.backup.clear();
        this.ready = true;
        this.emit({ type: 'reset' });
        break;
      case 'upsert': {
        // Our own post coming back: it takes the place of the note shown while waiting.
        const temp = msg.cid && this.pending.get(msg.cid);
        if (temp) { this.pending.delete(msg.cid); this.notes.delete(temp); }
        this.backup.delete(msg.note.id);
        const fresh = !temp && !this.notes.has(msg.note.id);
        this.notes.set(msg.note.id, msg.note);
        this.emit({ type: 'upsert', note: msg.note, fresh, cid: msg.cid, replaces: temp || undefined });
        break;
      }
      case 'remove': {
        const note = this.notes.get(msg.id);
        this.notes.delete(msg.id);
        this.backup.delete(msg.id);
        if (note) this.emit({ type: 'remove', note });
        break;
      }
      case 'drag': this.emit({ type: 'drag', id: msg.id, x: msg.x, y: msg.y }); break;
      case 'wdrag': this.emit({ type: 'wdrag', id: msg.id, wx: msg.wx, wy: msg.wy }); break;
      case 'batch': for (const item of msg.items || []) this.receive(item); break;
      case 'error': this.rollback(msg); this.emit({ type: 'error', code: msg.code, message: msg.message, id: msg.id }); break;
      default: break;
    }
  }

  raw(msg) {
    if (this.ws?.readyState === WebSocket.OPEN) { this.ws.send(JSON.stringify(msg)); return true; }
    return false;
  }

  send(msg) {
    if (msg.t === 'create') msg.cid ||= 'c' + Math.random().toString(36).slice(2, 12);
    if (this.raw(msg)) { this.applyLocally(msg); return true; }
    this.emit({ type: 'error', code: 'OFFLINE', message: 'Reconnecting… try again in a moment.' });
    return false;
  }

  /** Show a change before the server confirms it (see the top of this file). */
  applyLocally(msg) {
    const keep = n => { if (!this.backup.has(n.id)) this.backup.set(n.id, { ...n }); };
    if (msg.t === 'create') {
      const t = serverClock.now(), id = 'pending-' + msg.cid;
      const note = {
        id, board: msg.board, text: msg.text, color: msg.color, x: msg.x, y: msg.y,
        ...(msg.wx !== undefined ? { wx: msg.wx, wy: msg.wy } : {}),
        authorId: this.me?.id || '', authorName: this.me?.name || '', z: Number.MAX_SAFE_INTEGER, created: t, updated: t, v: 0, pending: true,
      };
      this.pending.set(msg.cid, id);
      this.notes.set(id, note);
      this.emit({ type: 'upsert', note, fresh: true });
      return;
    }
    const n = this.notes.get(msg.id);
    if (!n || n.pending) return;
    if (msg.t === 'move') { keep(n); n.x = msg.x; n.y = msg.y; }
    else if (msg.t === 'wmove') { keep(n); n.wx = msg.wx; n.wy = msg.wy; }
    else if (msg.t === 'edit') {
      keep(n);
      if (msg.text !== undefined) n.text = msg.text;
      if (msg.color !== undefined) n.color = msg.color;
      n.updated = serverClock.now();
      this.emit({ type: 'upsert', note: n, fresh: false });
    } else if (msg.t === 'delete') {
      keep(n);
      this.notes.delete(n.id);
      this.emit({ type: 'remove', note: n });
    }
  }

  /** The server refused a change: put back what it has. */
  rollback(msg) {
    const temp = msg.cid && this.pending.get(msg.cid);
    if (temp) {
      this.pending.delete(msg.cid);
      const note = this.notes.get(temp);
      this.notes.delete(temp);
      if (note) this.emit({ type: 'remove', note });
    }
    const before = msg.id && this.backup.get(msg.id);
    if (before) {
      this.backup.delete(msg.id);
      this.notes.set(before.id, before);
      this.emit({ type: 'upsert', note: before, fresh: false });
    }
  }

  countFor(board) {
    let n = 0;
    for (const note of this.notes.values()) if (note.board === board) n += 1;
    return n;
  }

  close() {
    this.closed = true;
    clearInterval(this.pinger);
    clearTimeout(this.reconnectTimer);
    try { this.ws?.close(); } catch { /* ignore */ }
    this.listeners.clear();
  }
}
