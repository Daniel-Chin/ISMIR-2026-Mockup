// One live connection per room ("welcome" or "session:PS-xx"). Keeps the authoritative
// note map from the server and fans events out to the board views that subscribe.

import { wsUrl, wsProtocols } from './api.js';

const PING_MS = 30_000;

export class Room {
  constructor(name) {
    this.name = name;
    this.notes = new Map();
    this.me = null;
    this.limits = { boardW: 1600, boardH: 1000, textMax: 600 };
    this.status = 'connecting';
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

  receive(msg) {
    switch (msg.t) {
      case 'hello':
        this.notes = new Map(msg.notes.map(n => [n.id, n]));
        this.me = msg.me;
        if (msg.limits) this.limits = msg.limits;
        this.emit({ type: 'reset' });
        break;
      case 'upsert': {
        const fresh = !this.notes.has(msg.note.id);
        this.notes.set(msg.note.id, msg.note);
        this.emit({ type: 'upsert', note: msg.note, fresh, cid: msg.cid });
        break;
      }
      case 'remove': {
        const note = this.notes.get(msg.id);
        this.notes.delete(msg.id);
        if (note) this.emit({ type: 'remove', note });
        break;
      }
      case 'drag': this.emit({ type: 'drag', id: msg.id, x: msg.x, y: msg.y }); break;
      case 'wdrag': this.emit({ type: 'wdrag', id: msg.id, wx: msg.wx, wy: msg.wy }); break;
      case 'batch': for (const item of msg.items || []) this.receive(item); break;
      case 'error': this.emit({ type: 'error', code: msg.code, message: msg.message, id: msg.id }); break;
      default: break;
    }
  }

  raw(msg) {
    if (this.ws?.readyState === WebSocket.OPEN) { this.ws.send(JSON.stringify(msg)); return true; }
    return false;
  }

  send(msg) {
    if (this.raw(msg)) return true;
    this.emit({ type: 'error', code: 'OFFLINE', message: 'Reconnecting… try again in a moment.' });
    return false;
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
