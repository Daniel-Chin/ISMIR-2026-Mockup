// The miniconf's paper search (static/js/papers.js, little_helpers.js), for the Warm-up
// Discussion. The miniconf builds it on jQuery + typeahead.js; this page allows no scripts from
// elsewhere (its CSP), so the same behaviour is written out here without them:
//
//   - one box, searching one field at a time: title, keyword or author (keyword by default);
//     switching field clears the search
//   - suggestions while typing: the field's values with a word that starts with each typed word,
//     ignoring case (Bloodhound's whitespace tokenizer), at most 20, matches in bold
//   - Enter or picking a suggestion searches; × clears
//   - title: the title contains the text (ignoring case); keyword / author: one of the paper's
//     keywords / authors is exactly the text, as picked from the suggestions

import { el } from './board.js';

const MODES = [
  { id: 'titles', label: 'title', tip: 'Search for paper titles' },
  { id: 'keywords', label: 'keyword', tip: 'Search for papers with specific keywords' },
  { id: 'authors', label: 'author', tip: 'Search for papers from specific authors' },
];
const DEFAULT_MODE = 'keywords';
const LIMIT = 20;

const tokens = text => String(text).toLowerCase().split(/\s+/).filter(Boolean);

/** Bloodhound's local search: values with, for every query word, a word starting with it. */
function suggest(values, query) {
  const q = tokens(query);
  if (!q.length) return [];
  const out = [];
  for (const v of values) {
    const words = tokens(v);
    if (q.every(t => words.some(w => w.startsWith(t)))) out.push(v);
    if (out.length === LIMIT) break;
  }
  return out;
}

/** The suggestion with the typed words in bold (typeahead's highlight: true). */
function highlighted(value, query) {
  const q = tokens(query).sort((a, b) => b.length - a.length).map(t => t.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
  const node = el('span');
  if (!q.length) { node.textContent = value; return node; }
  const re = new RegExp(`(${q.join('|')})`, 'gi');
  let last = 0;
  for (const m of value.matchAll(re)) {
    if (m.index > last) node.append(document.createTextNode(value.slice(last, m.index)));
    node.append(el('strong', '', m[0]));
    last = m.index + m[0].length;
  }
  if (last < value.length) node.append(document.createTextNode(value.slice(last)));
  return node;
}

const matches = {
  titles: (item, text) => item.title.toLowerCase().indexOf(text.toLowerCase()) > -1,
  keywords: (item, text) => item.keywords.indexOf(text) > -1,
  authors: (item, text) => item.authors.indexOf(text) > -1,
};

/**
 * A search box over `items` ({uid, title, keywords: [], authors: []}). `onChange(uids)` gets the
 * Set of matching uids, or null when nothing is searched.
 */
export class SearchBox {
  constructor(mount, { items, label = 'Search papers', onChange }) {
    this.items = items;
    this.onChange = onChange;
    this.values = {
      titles: items.map(i => i.title),
      keywords: [...new Set(items.flatMap(i => i.keywords))],
      authors: [...new Set(items.flatMap(i => i.authors))],
    };
    this.mode = DEFAULT_MODE;
    this.text = '';
    this.cursor = -1;

    this.root = el('div', 'pc-search');
    const field = el('div', 'pc-search-field');
    this.input = el('input', 'pc-search-input');
    Object.assign(this.input, { type: 'search', placeholder: 'Search', autocomplete: 'off', spellcheck: false });
    this.input.setAttribute('aria-label', label);
    this.input.setAttribute('role', 'combobox');
    this.input.setAttribute('aria-autocomplete', 'list');
    this.input.setAttribute('aria-expanded', 'false');
    const clear = el('button', 'pc-search-clear', '×');
    clear.type = 'button';
    clear.title = 'Clear the search';
    clear.addEventListener('click', () => { this.input.value = ''; this.search(''); this.input.focus(); });
    this.menu = el('div', 'pc-search-menu');
    this.menu.setAttribute('role', 'listbox');
    this.menu.hidden = true;
    field.append(this.input, clear, this.menu);

    this.seg = el('div', 'pc-seg');
    this.seg.setAttribute('role', 'group');
    this.seg.setAttribute('aria-label', 'Search by');
    for (const m of MODES) {
      const b = el('button', '', m.label);
      b.type = 'button'; b.dataset.mode = m.id; b.title = m.tip;
      b.addEventListener('click', () => this.setMode(m.id));
      this.seg.append(b);
    }
    this.count = el('span', 'pc-search-count');
    this.root.append(field, this.seg, this.count);
    mount.prepend(this.root);
    this.setMode(DEFAULT_MODE);

    this.input.addEventListener('input', () => this.openMenu());
    this.input.addEventListener('focus', () => this.openMenu());
    this.input.addEventListener('keydown', e => this.onKey(e));
    // Leaving the box closes the list (a click on a suggestion lands first, see below).
    this.input.addEventListener('blur', () => setTimeout(() => this.closeMenu(), 120));
    // A suggestion is picked on click, not on pointerdown: picked on the press, the list would
    // close at once and a phone's click, which follows the finger lifting, would land on what
    // lay under it (the title / keyword / author buttons, which clear the search). The press
    // only keeps the focus in the box.
    this.menu.addEventListener('pointerdown', e => { if (e.target.closest('[data-value]')) e.preventDefault(); });
    this.menu.addEventListener('mousedown', e => e.preventDefault());
    this.menu.addEventListener('click', e => {
      const opt = e.target.closest('[data-value]');
      if (opt) this.pick(opt.dataset.value);
    });
  }

  setMode(mode) {
    this.mode = mode;
    this.seg.querySelectorAll('button').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.mode === mode)));
    this.input.value = '';
    this.search('');
  }

  openMenu() {
    const list = suggest(this.values[this.mode], this.input.value);
    this.cursor = -1;
    this.menu.replaceChildren(...list.map((v, i) => {
      const opt = el('div', 'pc-search-option');
      opt.setAttribute('role', 'option');
      opt.dataset.value = v;
      opt.id = `${this.menuId ||= 'pc-search-' + Math.random().toString(36).slice(2)}-${i}`;
      opt.append(highlighted(v, this.input.value));
      return opt;
    }));
    this.menu.hidden = !list.length;
    this.input.setAttribute('aria-expanded', String(!!list.length));
  }

  closeMenu() {
    this.menu.hidden = true;
    this.cursor = -1;
    this.input.setAttribute('aria-expanded', 'false');
    this.input.removeAttribute('aria-activedescendant');
  }

  moveCursor(step) {
    const opts = [...this.menu.children];
    if (!opts.length || this.menu.hidden) return;
    const n = opts.length + 1;   // the options, and -1: back in the box
    this.cursor = ((this.cursor + 1 + step) % n + n) % n - 1;
    opts.forEach((o, i) => o.classList.toggle('is-cursor', i === this.cursor));
    if (this.cursor >= 0) {
      opts[this.cursor].scrollIntoView({ block: 'nearest' });
      this.input.setAttribute('aria-activedescendant', opts[this.cursor].id);
    } else this.input.removeAttribute('aria-activedescendant');
  }

  onKey(e) {
    if (e.key === 'ArrowDown') { e.preventDefault(); this.moveCursor(1); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); this.moveCursor(-1); }
    else if (e.key === 'Escape') this.closeMenu();
    else if (e.key === 'Enter') {
      e.preventDefault();
      const opt = this.cursor >= 0 ? this.menu.children[this.cursor] : null;
      if (opt) this.pick(opt.dataset.value);
      else { this.closeMenu(); this.search(this.input.value); }
    }
  }

  pick(value) {
    this.input.value = value;
    this.closeMenu();
    this.search(value);
  }

  /** Search the current field for `text` ('' shows everything again). */
  search(text) {
    this.text = text;
    const test = matches[this.mode];
    const found = text ? new Set(this.items.filter(i => test(i, text)).map(i => String(i.uid))) : null;
    this.count.textContent = found ? `${found.size} of ${this.items.length}` : '';
    this.root.classList.toggle('is-active', !!found);
    this.onChange(found);
  }

  /** Back to no search (e.g. a link to a paper the search hides). */
  clear() {
    if (!this.text) return;
    this.input.value = '';
    this.search('');
  }
}
