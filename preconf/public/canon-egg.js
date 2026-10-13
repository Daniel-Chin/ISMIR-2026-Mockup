// Canon-in-D piano easter egg, ported verbatim from live_overview/overview-source/app.js
// so the Lounge hero behaves exactly like the live overview's. Only the paper pool differs
// (program.json instead of live state) and there is no debug mode here.
(function () {
'use strict';
const debugMode = false;

// v8.84 hidden Canon-in-D piano easter egg. Deliberately no visible hint.
const CANON_EGG_SEQUENCE = ['D', 'A', 'B', 'F', 'G', 'D', 'G', 'A'];
const CANON_EGG_DEGREE_TO_KEY = { '1': 'D', '5': 'A', '6': 'B', '3': 'F', '4': 'G' };
const CANON_EGG_CHORDS = {
  D: { visual: ['D', 'F#', 'A'], midi: [62, 66, 69] },
  A: { visual: ['C#', 'E', 'A'], midi: [57, 61, 64] },
  B: { visual: ['D', 'F#', 'B'], midi: [59, 62, 66] }, // Bm
  F: { visual: ['C#', 'F#', 'A'], midi: [54, 57, 61] }, // F#m
  G: { visual: ['D', 'G', 'B'], midi: [55, 59, 62] },
};
const CANON_EGG_ROOT_NOTE_TO_KEY = { D: 'D', A: 'A', B: 'B', 'F#': 'F', G: 'G' };
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
const canonEggHeldKeys = new Set();

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
  const chord = CANON_EGG_CHORDS[key];
  if (!ctx || !chord) return;
  const start = when == null ? ctx.currentTime + .005 : when;
  const duration = options.duration || 1.05;
  const velocity = options.velocity || .105;
  const spread = options.spread == null ? .014 : options.spread;
  chord.midi.forEach((midi, index) => canonEggPianoNote(midi, start + index * spread, duration, velocity * (index === 0 ? 1 : .88)));
}

function canonEggPlaySuccessPhrase() {
  const ctx = canonEggAudio();
  if (!ctx) return;
  const start = ctx.currentTime + .12;
  const beat = .42;
  const bass = [50, 45, 47, 42, 43, 50, 43, 45];
  const upper = [
    [62,66,69], [61,64,69], [62,66,71], [61,66,69],
    [62,67,71], [62,66,69], [62,67,71], [61,64,69],
  ];
  upper.forEach((notes, step) => {
    const t = start + step * beat;
    canonEggPianoNote(bass[step], t, beat * 1.5, .075);
    notes.forEach((midi, index) => canonEggPianoNote(midi + 12, t + index * (beat / 4), beat * .95, .072));
  });
  const resolve = start + upper.length * beat;
  [50, 62, 66, 69, 74].forEach((midi, index) => canonEggPianoNote(midi, resolve + index * .04, 1.55, index === 0 ? .08 : .068));
}

function canonEggCreatePianoOverlay() {
  const hero = document.querySelector('.home-hero .hero-copy');
  if (!hero || canonEggPianoOverlay) return;
  const overlay = document.createElement('div');
  overlay.className = 'canon-egg-piano-overlay';
  overlay.setAttribute('aria-hidden', 'true');
  Object.entries(CANON_EGG_NOTE_GEOMETRY).forEach(([note, geometry]) => {
    const node = document.createElement('i');
    node.className = `canon-egg-piano-key ${geometry.black ? 'black' : 'white'}`;
    node.dataset.canonNote = note;
    const chordKey = CANON_EGG_ROOT_NOTE_TO_KEY[note];
    if (chordKey) {
      node.dataset.canonRoot = chordKey;
      node.classList.add('is-root-trigger');
    }
    overlay.appendChild(node);
  });
  hero.appendChild(overlay);
  canonEggPianoOverlay = overlay;
  canonEggLayoutPiano();
}

function canonEggLayoutPiano() {
  if (!canonEggPianoOverlay) return;
  const width = canonEggPianoOverlay.clientWidth;
  if (!width) return;
  const octaveWidth = 112;
  const maxStart = Math.max(0, width - octaveWidth);
  let octaveStart = Math.round((width / 2 - octaveWidth / 2) / octaveWidth) * octaveWidth;
  octaveStart = Math.max(0, Math.min(maxStart, octaveStart));
  Object.entries(CANON_EGG_NOTE_GEOMETRY).forEach(([note, geometry]) => {
    const node = canonEggPianoOverlay.querySelector(`[data-canon-note="${note}"]`);
    if (!node) return;
    node.style.left = `${octaveStart + geometry.x}px`;
    node.style.width = `${geometry.width}px`;
    node.style.height = `${geometry.height}px`;
  });
}

function canonEggRenderPressedKeys() {
  if (!canonEggPianoOverlay) return;
  const activeNotes = new Set();
  canonEggHeldKeys.forEach((key) => (CANON_EGG_CHORDS[key]?.visual || []).forEach((note) => activeNotes.add(note)));
  canonEggPianoOverlay.querySelectorAll('[data-canon-note]').forEach((node) => node.classList.toggle('is-pressed', activeNotes.has(node.dataset.canonNote)));
}

function canonEggRenderProgress() {
  canonEggBinaryGroups.forEach((group, index) => group.classList.toggle('canon-egg-lit', index < canonEggProgress));
}

function canonEggPaperPool() {
  // Only papers with an author-provided fun fact are eligible.
  return Object.values(window.PC_PROGRAM?.papers || {})
    .filter((paper) => String(paper?.funFact || '').trim())
    .map((paper) => ({ id: paper.uid, title: String(paper.title || paper.uid), fact: String(paper.funFact).trim() }));
}

function canonEggCloseFunFact() {
  document.querySelector('.canon-egg-funfact-backdrop')?.remove();
  canonEggCompleted = false;
  canonEggProgress = 0;
  canonEggRenderProgress();
}

function canonEggShowFunFact() {
  const pool = canonEggPaperPool();
  // No fun facts yet: reset so the puzzle can be played again instead of staying "completed".
  if (!pool.length) { canonEggCloseFunFact(); return; }
  const paper = pool[Math.floor(Math.random() * pool.length)];
  const backdrop = document.createElement('div');
  backdrop.className = 'canon-egg-funfact-backdrop';
  backdrop.innerHTML = `<section class="canon-egg-funfact-dialog" role="dialog" aria-modal="true" aria-labelledby="canon-egg-title">
    <span class="canon-egg-funfact-kicker">Paper fun fact</span>
    <h3 id="canon-egg-title"></h3>
    <p class="canon-egg-funfact-copy"></p>
    <button class="canon-egg-funfact-close" type="button">Close</button>
  </section>`;
  backdrop.querySelector('#canon-egg-title').textContent = paper.title;
  backdrop.querySelector('.canon-egg-funfact-copy').textContent = paper.fact;
  const close = backdrop.querySelector('.canon-egg-funfact-close');
  close.addEventListener('click', canonEggCloseFunFact);
  backdrop.addEventListener('click', (event) => { if (event.target === backdrop) canonEggCloseFunFact(); });
  document.body.appendChild(backdrop);
  requestAnimationFrame(() => backdrop.classList.add('is-visible'));
  close.focus({ preventScroll: true });
}

function canonEggAdvance(key) {
  if (canonEggCompleted) return;
  if (CANON_EGG_SEQUENCE[canonEggProgress] === key) {
    canonEggProgress += 1;
    canonEggRenderProgress();
    if (canonEggProgress === CANON_EGG_SEQUENCE.length) {
      canonEggCompleted = true;
      canonEggPlaySuccessPhrase();
      canonEggShowFunFact();
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
  if (debugMode || event.isComposing || event.repeat || event.ctrlKey || event.metaKey || event.altKey || canonEggEditableTarget(event.target)) return;
  const key = canonEggKeyboardChord(event);
  if (!key) return;
  canonEggHeldKeys.add(key);
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
  if (debugMode || canonEggCompleted) return;
  const root = event.target.closest?.('[data-canon-root]');
  if (!root || !canonEggPianoOverlay?.contains(root)) return;
  const key = root.dataset.canonRoot || '';
  if (!CANON_EGG_CHORDS[key]) return;
  event.preventDefault();
  canonEggPointerKey = key;
  canonEggPointerId = event.pointerId;
  try { root.setPointerCapture?.(event.pointerId); } catch (_) {}
  canonEggHeldKeys.add(key);
  canonEggRenderPressedKeys();
  canonEggPlayChord(key);
  canonEggAdvance(key);
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
  if (debugMode) return;
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

window.addEventListener('keydown', (event) => {
  if (event.key === 'Escape' && document.querySelector('.canon-egg-funfact-backdrop')) canonEggCloseFunFact();
});
window.addEventListener('resize', canonEggLayoutPiano);
})();
