// Canon-in-D piano easter egg, shared by the Warm-up Discussion (lounge.html) and the Live
// Overview (live.html; its build copies this file). Solving it counts: the first time a signed-in
// attendee solves it they learn which finder they are; every later solve shows a random paper
// fun fact. Both link to the list of finders.
//
// The page provides:
//   window.PC_EGG        sign-in and the finders' list ({user, login, solve, leaderboard}): app.js
//                        in the lounge, egg-account.js in the live overview. Without it the egg
//                        shows fun facts only.
//   window.PC_EGG_POOL   optional () => [{id, title, fact, url}]: papers with a fun fact
//                        (default: window.PC_PROGRAM, the lounge's program.json)
(function () {
'use strict';

// v8.84 hidden Canon-in-D piano easter egg. Deliberately no visible hint.
const CANON_EGG_SEQUENCE = ['D', 'A', 'B', 'F', 'G', 'D', 'G', 'A'];
const CANON_EGG_DEGREE_TO_KEY = { '1': 'D', '5': 'A', '6': 'B', '3': 'F', '4': 'G' };
// Pachelbel's Canon: D A Bm F#m G D G A (I V vi iii IV I IV V), one voicing per step. The root is
// always in the bass (the Canon's bass line D2 A2 B2 F#2 G2 D2 G2 A2); the three upper voices hold
// common tones or move against the bass, so there are no parallel fifths or octaves, the loop back
// to D included. G has two voicings, by step. The piano lights the three upper voices, at their
// octaves. MIDI 60 = C4.
const CANON_EGG_VOICINGS = [
  { bass: 38, midi: [54, 57, 62] }, // I    D    D2  | F#3 A3 D4
  { bass: 45, midi: [52, 57, 61] }, // V    A    A2  | E3 A3 C#4
  { bass: 47, midi: [50, 54, 59] }, // vi   Bm   B2  | D3 F#3 B3
  { bass: 42, midi: [54, 57, 61] }, // iii  F#m  F#2 | F#3 A3 C#4
  { bass: 43, midi: [50, 55, 59] }, // IV   G    G2  | D3 G3 B3
  { bass: 38, midi: [54, 57, 62] }, // I    D    D2  | F#3 A3 D4
  { bass: 43, midi: [55, 59, 62] }, // IV   G    G2  | G3 B3 D4
  { bass: 45, midi: [52, 57, 61] }, // V    A    A2  | E3 A3 C#4
];
// A chord's voicing when played out of turn: that of its first step. B is Bm, F is F#m.
const CANON_EGG_CHORDS = { D: CANON_EGG_VOICINGS[0], A: CANON_EGG_VOICINGS[1], B: CANON_EGG_VOICINGS[2], F: CANON_EGG_VOICINGS[3], G: CANON_EGG_VOICINGS[4] };
/** The voicing for `key` now: the next step's, if `key` is the chord that step expects. */
function canonEggVoicing(key) {
  return CANON_EGG_SEQUENCE[canonEggProgress] === key ? CANON_EGG_VOICINGS[canonEggProgress] : CANON_EGG_CHORDS[key];
}
const CANON_EGG_ROOT_NOTE_TO_KEY = { D: 'D', A: 'A', B: 'B', 'F#': 'F', G: 'G' };
// The overlay covers two octaves of the drawn keyboard, 3 (C3-B3) and 4 (C4-B4) around the
// middle, where the chords' upper voices lie. Clicking a root in either octave plays its chord.
const CANON_EGG_OCTAVES = [3, 4];
const CANON_EGG_NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
const canonEggNoteName = (midi) => CANON_EGG_NOTE_NAMES[midi % 12] + (Math.floor(midi / 12) - 1);   // 62 -> 'D4'
const CANON_EGG_NOTE_GEOMETRY = {
  'C#': { x: 12, width: 8, height: 16, black: true },
  D: { x: 16, width: 15, height: 24, black: false },
  E: { x: 32, width: 15, height: 24, black: false },
  'F#': { x: 60, width: 8, height: 16, black: true },
  G: { x: 64, width: 15, height: 24, black: false },
  A: { x: 80, width: 15, height: 24, black: false },
  B: { x: 96, width: 15, height: 24, black: false },
};
let canonEggAudioContext = null;
let canonEggMaster = null;
let canonEggProgress = 0;
let canonEggCompleted = false;
let canonEggPianoOverlay = null;
let canonEggPointerKey = '';
let canonEggPointerId = null;
let canonEggBinaryGroups = [];
// Chords held down (key -> the upper voices played), so the keys lit are the very notes heard.
const canonEggHeldKeys = new Map();

function canonEggAudio() {
  const AudioCtor = window.AudioContext || window.webkitAudioContext;
  if (!AudioCtor) return null;
  if (!canonEggAudioContext) {
    try {
      canonEggAudioContext = new AudioCtor();
      canonEggMaster = canonEggAudioContext.createGain();
      canonEggMaster.gain.value = 0.72;
      const compressor = canonEggAudioContext.createDynamicsCompressor();
      compressor.threshold.value = -18;
      compressor.knee.value = 18;
      compressor.ratio.value = 5;
      compressor.attack.value = 0.004;
      compressor.release.value = 0.18;
      canonEggMaster.connect(compressor);
      compressor.connect(canonEggAudioContext.destination);
    } catch (_) { return null; }
  }
  if (canonEggAudioContext.state === 'suspended') canonEggAudioContext.resume().catch(() => {});
  return canonEggAudioContext;
}

function canonEggMidiFrequency(midi) {
  return 440 * Math.pow(2, (Number(midi) - 69) / 12);
}

function canonEggPianoNote(midi, when, duration = 1.05, velocity = 0.11) {
  const ctx = canonEggAudio();
  if (!ctx || !canonEggMaster) return;
  const start = Math.max(ctx.currentTime, Number(when) || ctx.currentTime);
  const end = start + Math.max(0.2, duration);
  const frequency = canonEggMidiFrequency(midi);
  const filter = ctx.createBiquadFilter();
  const envelope = ctx.createGain();
  filter.type = 'lowpass';
  filter.frequency.setValueAtTime(Math.min(5200, 2400 + frequency * 5), start);
  filter.frequency.exponentialRampToValueAtTime(Math.max(900, frequency * 3), end);
  filter.Q.value = 0.35;
  envelope.gain.setValueAtTime(0.0001, start);
  envelope.gain.exponentialRampToValueAtTime(Math.max(0.001, velocity), start + 0.007);
  envelope.gain.exponentialRampToValueAtTime(Math.max(0.0005, velocity * 0.30), start + 0.09);
  envelope.gain.exponentialRampToValueAtTime(0.0001, end);
  envelope.connect(filter);
  filter.connect(canonEggMaster);
  const partials = [[1, 'triangle', 1.0, 0], [2, 'sine', .24, 1.3], [3, 'sine', .10, -1.8], [4, 'sine', .045, 2.4]];
  partials.forEach(([ratio, type, level, detune]) => {
    const osc = ctx.createOscillator();
    const gain = ctx.createGain();
    osc.type = type;
    osc.frequency.setValueAtTime(frequency * ratio, start);
    osc.detune.setValueAtTime(detune, start);
    gain.gain.value = level;
    osc.connect(gain); gain.connect(envelope);
    osc.start(start); osc.stop(end + .04);
  });
}

function canonEggPlayChord(key, when = null, options = {}) {
  const ctx = canonEggAudio();
  const chord = CANON_EGG_CHORDS[key] && canonEggVoicing(key);
  if (!ctx || !chord) return;
  const start = when == null ? ctx.currentTime + .005 : when;
  const duration = options.duration || 1.05;
  const velocity = options.velocity || .105;
  const spread = options.spread == null ? .014 : options.spread;
  // The root in the bass first, a touch softer and longer (as the success phrase plays it), then the right hand.
  canonEggPianoNote(chord.bass, start, duration * 1.3, velocity * .8);
  chord.midi.forEach((midi, index) => canonEggPianoNote(midi, start + (index + 1) * spread, duration, velocity * (index === 0 ? 1 : .88)));
}

function canonEggPlaySuccessPhrase() {
  const ctx = canonEggAudio();
  if (!ctx) return;
  const start = ctx.currentTime + .12;
  const beat = .42;
  // The progression, step by step, the upper voices an octave higher to ring out.
  const bass = CANON_EGG_VOICINGS.map((v) => v.bass);
  const upper = CANON_EGG_VOICINGS.map((v) => v.midi);
  upper.forEach((notes, step) => {
    const t = start + step * beat;
    canonEggPianoNote(bass[step], t, beat * 1.5, .075);
    notes.forEach((midi, index) => canonEggPianoNote(midi + 12, t + index * (beat / 4), beat * .95, .072));
  });
  const resolve = start + upper.length * beat;
  [38, 62, 66, 69, 74].forEach((midi, index) => canonEggPianoNote(midi, resolve + index * .04, 1.55, index === 0 ? .08 : .068));
}

function canonEggCreatePianoOverlay() {
  const hero = document.querySelector('.home-hero .hero-copy');
  if (!hero || canonEggPianoOverlay) return;
  const overlay = document.createElement('div');
  overlay.className = 'canon-egg-piano-overlay';
  overlay.setAttribute('aria-hidden', 'true');
  CANON_EGG_OCTAVES.forEach((octave) => Object.entries(CANON_EGG_NOTE_GEOMETRY).forEach(([note, geometry]) => {
    const node = document.createElement('i');
    node.className = `canon-egg-piano-key ${geometry.black ? 'black' : 'white'}`;
    node.dataset.canonNote = note + octave;   // 'D4', 'F#3', …
    const chordKey = CANON_EGG_ROOT_NOTE_TO_KEY[note];
    if (chordKey) {
      node.dataset.canonRoot = chordKey;
      node.classList.add('is-root-trigger');
    }
    overlay.appendChild(node);
  }));
  hero.appendChild(overlay);
  canonEggPianoOverlay = overlay;
  canonEggLayoutPiano();
}

function canonEggLayoutPiano() {
  if (!canonEggPianoOverlay) return;
  const width = canonEggPianoOverlay.clientWidth;
  if (!width) return;
  const octaveWidth = 112;
  // Octave 4 is the drawn octave nearest the middle, octave 3 the one left of it (both on screen).
  const maxStart = Math.max(octaveWidth, width - octaveWidth);
  let octave4 = Math.round((width / 2) / octaveWidth) * octaveWidth;
  octave4 = Math.max(octaveWidth, Math.min(maxStart, octave4));
  CANON_EGG_OCTAVES.forEach((octave) => Object.entries(CANON_EGG_NOTE_GEOMETRY).forEach(([note, geometry]) => {
    const node = canonEggPianoOverlay.querySelector(`[data-canon-note="${note + octave}"]`);
    if (!node) return;
    node.style.left = `${octave4 + (octave - 4) * octaveWidth + geometry.x}px`;
    node.style.width = `${geometry.width}px`;
    node.style.height = `${geometry.height}px`;
  }));
}

function canonEggRenderPressedKeys() {
  if (!canonEggPianoOverlay) return;
  const activeNotes = new Set();
  canonEggHeldKeys.forEach((midi) => midi.forEach((m) => activeNotes.add(canonEggNoteName(m))));
  canonEggPianoOverlay.querySelectorAll('[data-canon-note]').forEach((node) => node.classList.toggle('is-pressed', activeNotes.has(node.dataset.canonNote)));
}

function canonEggRenderProgress() {
  canonEggBinaryGroups.forEach((group, index) => group.classList.toggle('canon-egg-lit', index < canonEggProgress));
}

function canonEggPaperPool() {
  if (typeof window.PC_EGG_POOL === 'function') return window.PC_EGG_POOL();
  // Only papers with an author-provided fun fact are eligible.
  return Object.values(window.PC_PROGRAM?.papers || {})
    // "NA", "N/A", "none", "-": placeholders, not facts.
    .filter((paper) => !/^(n\/?a\.?|none|nil|-+)?$/i.test(String(paper?.funFact || '').trim()))
    .map((paper) => ({ id: paper.uid, title: String(paper.title || paper.uid), fact: String(paper.funFact).trim(), url: /^https:\/\//.test(paper.posterUrl || '') ? paper.posterUrl : '' }));
}

function canonEggCloseFunFact() {
  document.querySelector('.canon-egg-funfact-backdrop')?.remove();
  // Closing the message gives up its sign-in: a later sign-in no longer claims a place.
  canonEggStore.set(CANON_EGG_PENDING_KEY, null);
  canonEggCompleted = false;
  canonEggProgress = 0;
  canonEggRenderProgress();
}

// ---------- result dialog: congratulations / fun fact / leaderboard ----------
const CANON_EGG_FOUND_KEY = 'pcEggFound';       // this browser has solved it before
// Set (to the time) when "Sign in" is pressed in the message: the rank is claimed on return,
// within CANON_EGG_PENDING_MS. Solving signed out and signing in some other way never counts.
const CANON_EGG_PENDING_KEY = 'pcEggPending';
const CANON_EGG_PENDING_MS = 15 * 60 * 1000;
const CANON_EGG_FACTS_NOTE = 'From now on, every time you solve it you will get a random paper fun fact.';
const canonEggStore = {
  get(k) { try { return localStorage.getItem(k); } catch (_) { return null; } },
  set(k, v) { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (_) {} },
};

function canonEggOrdinal(n) {
  const tail = n % 100 >= 11 && n % 100 <= 13 ? 'th' : ({ 1: 'st', 2: 'nd', 3: 'rd' }[n % 10] || 'th');
  return n + tail;
}

/** Open the dialog (once) and show `view`: {kind: 'congrats'|'congrats-signin'|'fact'|'leaderboard', ...}. */
function canonEggOpenDialog(view) {
  let backdrop = document.querySelector('.canon-egg-funfact-backdrop');
  if (!backdrop) {
    backdrop = document.createElement('div');
    backdrop.className = 'canon-egg-funfact-backdrop';
    backdrop.innerHTML = `<section class="canon-egg-funfact-dialog" role="dialog" aria-modal="true" aria-labelledby="canon-egg-title">
      <span class="canon-egg-funfact-kicker"></span>
      <h3 id="canon-egg-title"></h3>
      <div class="canon-egg-funfact-copy"></div>
      <p class="canon-egg-links"></p>
      <button class="canon-egg-funfact-close" type="button">Close</button>
    </section>`;
    backdrop.querySelector('.canon-egg-funfact-close').addEventListener('click', canonEggCloseFunFact);
    backdrop.addEventListener('click', (event) => { if (event.target === backdrop) canonEggCloseFunFact(); });
    document.body.appendChild(backdrop);
    requestAnimationFrame(() => backdrop.classList.add('is-visible'));
    backdrop.querySelector('.canon-egg-funfact-close').focus({ preventScroll: true });
  }
  canonEggRender(backdrop, view);
}

function canonEggLink(label, run) {
  const a = document.createElement('a');
  a.className = 'canon-egg-link';
  a.href = '#';
  a.setAttribute('role', 'button');
  a.textContent = label;
  a.addEventListener('click', (event) => { event.preventDefault(); run(); });
  return a;
}

function canonEggRender(backdrop, view) {
  const kicker = backdrop.querySelector('.canon-egg-funfact-kicker');
  const title = backdrop.querySelector('#canon-egg-title');
  const copy = backdrop.querySelector('.canon-egg-funfact-copy');
  const links = backdrop.querySelector('.canon-egg-links');
  const para = (text) => { const p = document.createElement('p'); p.textContent = text; return p; };
  const toBoard = () => canonEggLink('See who found the easter egg →', () => canonEggOpenDialog({ kind: 'leaderboard' }));
  // Signed out: every message after a solve offers to record the find. Signing in from here (and
  // only from here) records it once the visitor is back (canonEggClaimPending).
  const signedOut = !window.PC_EGG?.user;
  const toSignIn = () => canonEggLink('Sign in to record your find →', () => {
    canonEggStore.set(CANON_EGG_PENDING_KEY, String(Date.now()));
    window.PC_EGG?.login();
  });
  copy.replaceChildren();
  links.replaceChildren();
  backdrop.dataset.view = view.kind;
  if (view.kind === 'congrats') {
    kicker.textContent = 'Easter egg found';
    title.textContent = 'Congratulations!';
    // rank 0: the server has not answered yet (canonEggShowResult).
    copy.append(para(view.rank ? `You are the ${canonEggOrdinal(view.rank)} person to find the hidden easter egg!` : 'You found the hidden easter egg! Recording your find…'), para(CANON_EGG_FACTS_NOTE));
    links.append(toBoard());
  } else if (view.kind === 'congrats-signin') {
    kicker.textContent = 'Easter egg found';
    title.textContent = 'Congratulations!';
    copy.append(para('You found the hidden easter egg! Sign in with Slack to record that you found it.'), para(CANON_EGG_FACTS_NOTE));
    links.append(toSignIn(), toBoard());
  } else if (view.kind === 'fact') {
    const pool = canonEggPaperPool();
    const paper = pool[Math.floor(Math.random() * pool.length)];
    kicker.textContent = 'Paper fun fact';
    // The paper's title opens its miniconf page in a new tab.
    title.textContent = paper && !paper.url ? paper.title : paper ? '' : 'Fun facts are on their way';
    if (paper?.url) {
      const a = document.createElement('a');
      a.className = 'canon-egg-paper-link';
      a.href = paper.url; a.target = '_blank'; a.rel = 'noopener noreferrer';
      a.textContent = paper.title;
      title.append(a);
    }
    copy.append(para(paper ? paper.fact : 'Authors are still sending them in. Solve it again later!'));
    if (window.PC_EGG) {   // no sign-in or finders' list on a page without them
      if (signedOut) links.append(toSignIn());
      links.append(toBoard());
    }
  } else if (view.kind === 'leaderboard') {
    kicker.textContent = 'Easter egg finders';
    title.textContent = view.rank ? 'Congratulations!' : 'Who found the easter egg';
    copy.append(para('Loading…'));
    if (signedOut) links.append(toSignIn());
    const api = window.PC_EGG;
    if (!api) { copy.replaceChildren(para('The list of finders is not available here.')); return; }
    api.leaderboard().then((data) => {
      if (!data?.ok) throw new Error('leaderboard');
      copy.replaceChildren();
      // Just claimed after signing in from the message: say so above the list.
      if (view.rank) copy.append(para(`You are the ${canonEggOrdinal(view.rank)} person to find the hidden easter egg!`), para(CANON_EGG_FACTS_NOTE));
      if (!data.entries.length) { copy.append(para('Nobody has found it yet.')); return; }
      const when = new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
      // Names only, several per line, in the order they found it: no rank numbers, nobody is
      // singled out. When each one found it shows on hover.
      const chip = (e, me) => {
        const li = document.createElement('li');
        if (me) li.classList.add('is-me');
        li.textContent = e.name + (me ? ' (you)' : '');
        li.title = `${e.name} · ${when.format(new Date(e.at))}`;
        return li;
      };
      // The names scroll inside the dialog however many finders there are.
      const list = document.createElement('ol');
      list.className = 'canon-egg-board';
      for (const e of data.entries) list.append(chip(e, e.me));
      // Further on than the list goes: you, after a gap mark.
      if (data.mine && data.mine.rank > data.entries.length) {
        const gap = document.createElement('li');
        gap.className = 'canon-egg-gap';
        gap.setAttribute('aria-hidden', 'true');
        gap.textContent = '\u22EF';
        list.append(gap, chip(data.mine, true));
      }
      copy.append(list);
      const more = [`${data.total} ${data.total === 1 ? 'person has' : 'people have'} found it so far.`];
      if (data.total > data.entries.length) more.push(`Showing the first ${data.entries.length}.`);
      if (!api.user) more.push('You are not signed in, so your find is not recorded yet.');
      copy.append(para(more.join(' ')));
      // Your name in view (scrolls the list only, not the page).
      const mineInList = list.querySelector('.is-me');
      if (mineInList) list.scrollTop = mineInList.offsetTop - list.clientHeight / 2;
    }).catch(() => { copy.replaceChildren(para('Could not load the list. Try again in a moment.')); });
  }
}

/**
 * Solved. Signed in: the server records it; the first time, show the rank. Signed out, first
 * time on this browser: congratulate and offer sign-in; only signing in from that message
 * claims a place. Every other solve: a random paper fun fact.
 *
 * The message opens at once, with the music: what this browser knows decides it (found here
 * before? then a fun fact). The server's answer, a second or two later, only fills in the rank,
 * or turns a fun fact into the congratulations if it was a first find after all.
 */
let canonEggSolveId = 0;
function canonEggShowResult() {
  const api = window.PC_EGG;
  const foundHere = !!canonEggStore.get(CANON_EGG_FOUND_KEY);
  canonEggStore.set(CANON_EGG_FOUND_KEY, '1');
  if (!api?.user) {
    canonEggOpenDialog({ kind: api && !foundHere ? 'congrats-signin' : 'fact' });
    return;
  }
  const id = ++canonEggSolveId;
  canonEggOpenDialog(foundHere ? { kind: 'fact' } : { kind: 'congrats', rank: 0 });
  // Still showing this solve's message (not closed, not moved on to the list of finders)?
  const current = (kind) => id === canonEggSolveId && document.querySelector(`.canon-egg-funfact-backdrop[data-view="${kind}"]`);
  api.solve().then((r) => {
    if (r?.ok && r.first) { if (current('congrats') || current('fact')) canonEggOpenDialog({ kind: 'congrats', rank: r.rank }); }
    else if (current('congrats')) canonEggOpenDialog({ kind: 'fact' });   // found before, on another device
  }).catch(() => { if (current('congrats')) canonEggOpenDialog({ kind: 'fact' }); });   // offline: not recorded
}

/** Back from "Sign in" in the message: claim the place and show the leaderboard with it. */
async function canonEggClaimPending() {
  const api = window.PC_EGG;
  const pressed = Number(canonEggStore.get(CANON_EGG_PENDING_KEY)) || 0;
  if (!pressed) return;
  if (!api?.user) return;   // sign-in still under way (e.g. in the Slack app): keep waiting
  canonEggStore.set(CANON_EGG_PENDING_KEY, null);
  if (Date.now() - pressed > CANON_EGG_PENDING_MS) return;
  try {
    const r = await api.solve();
    if (r?.ok) canonEggOpenDialog({ kind: 'leaderboard', rank: r.first ? r.rank : 0 });
  } catch (_) { /* offline: the place is not claimed */ }
}

function canonEggAdvance(key) {
  if (canonEggCompleted) return;
  if (CANON_EGG_SEQUENCE[canonEggProgress] === key) {
    canonEggProgress += 1;
    canonEggRenderProgress();
    if (canonEggProgress === CANON_EGG_SEQUENCE.length) {
      canonEggCompleted = true;
      canonEggPlaySuccessPhrase();
      canonEggShowResult();
    }
    return;
  }
  // Strict reset: a wrong mapped chord turns every progress light off and the
  // next chord starts a new attempt.
  canonEggProgress = 0;
  canonEggRenderProgress();
}

// Keep native new-tab anchors for keyboard/context-menu use and blocked popups.
// A plain primary click also requests focus; the browser owns the final tab policy.
function canonEggEditableTarget(target) {
  if (!(target instanceof Element)) return false;
  return Boolean(target.closest('input, textarea, select, [contenteditable="true"]'));
}

function canonEggKeyboardChord(event) {
  const codeMatch = /^Key([DABFG])$/.exec(String(event.code || ''));
  const keyText = String(event.key || '').toUpperCase();
  // event.key supports both the number row and NumLock-enabled number pad,
  // without interpreting navigation keys or shifted punctuation as notes.
  return codeMatch?.[1] || (['D', 'A', 'B', 'F', 'G'].includes(keyText) ? keyText : CANON_EGG_DEGREE_TO_KEY[keyText] || '');
}

function canonEggKeyDown(event) {
  if (event.isComposing || event.repeat || event.ctrlKey || event.metaKey || event.altKey || canonEggEditableTarget(event.target)) return;
  const key = canonEggKeyboardChord(event);
  if (!key) return;
  canonEggPress(key);
}

/** A chord pressed (keyboard or piano): light its upper voices, play it, then score it. */
function canonEggPress(key) {
  canonEggHeldKeys.set(key, canonEggVoicing(key).midi);   // before advancing: this step's voicing
  canonEggRenderPressedKeys();
  canonEggPlayChord(key);
  canonEggAdvance(key);
}

function canonEggKeyUp(event) {
  const key = canonEggKeyboardChord(event);
  if (!key) return;
  canonEggHeldKeys.delete(key);
  canonEggRenderPressedKeys();
}

function canonEggPointerDown(event) {
  if (canonEggCompleted) return;
  const root = event.target.closest?.('[data-canon-root]');
  if (!root || !canonEggPianoOverlay?.contains(root)) return;
  const key = root.dataset.canonRoot || '';
  if (!CANON_EGG_CHORDS[key]) return;
  event.preventDefault();
  canonEggPointerKey = key;
  canonEggPointerId = event.pointerId;
  try { root.setPointerCapture?.(event.pointerId); } catch (_) {}
  canonEggPress(key);
}

function canonEggPointerUp(event) {
  if (!canonEggPointerKey) return;
  if (canonEggPointerId != null && event.pointerId != null && event.pointerId !== canonEggPointerId) return;
  canonEggHeldKeys.delete(canonEggPointerKey);
  canonEggPointerKey = '';
  canonEggPointerId = null;
  canonEggRenderPressedKeys();
}

function initCanonEasterEgg() {
  canonEggCreatePianoOverlay();
  canonEggBinaryGroups = [...document.querySelectorAll('.llm-prompt-card .binary-puzzle .bit-group')].slice(0, CANON_EGG_SEQUENCE.length);
  canonEggRenderProgress();
  window.addEventListener('keydown', canonEggKeyDown);
  window.addEventListener('keyup', canonEggKeyUp);
  canonEggPianoOverlay?.addEventListener('pointerdown', canonEggPointerDown);
  window.addEventListener('pointerup', canonEggPointerUp);
  window.addEventListener('pointercancel', canonEggPointerUp);
  window.addEventListener('blur', () => {
    canonEggHeldKeys.clear();
    canonEggPointerKey = '';
    canonEggPointerId = null;
    canonEggRenderPressedKeys();
  });
}

initCanonEasterEgg();
// app.js sets up window.PC_EGG first and announces 'pc-egg-ready' once the sign-in check is
// back (this script is deferred, so PC_EGG may already exist with a remembered user): try both.
if (window.PC_EGG) canonEggClaimPending();
window.addEventListener('pc-egg-ready', canonEggClaimPending, { once: true });

window.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && document.querySelector('.canon-egg-funfact-backdrop')) canonEggCloseFunFact();
});
window.addEventListener('resize', canonEggLayoutPiano);
})();
