// The page header both sites share (Live Overview and Warm-up Discussion): the Lights Off / On
// theme and, below 1100px wide, the nav behind a menu button.
//
// Load it synchronously in <head>, after the stylesheets, so the page never flashes the wrong
// theme. Expects #theme-toggle, and #nav-toggle + #main-nav for the menu (each optional).
(function () {
  'use strict';
  const KEY = 'ismirColorTheme';   // one setting for both sites
  const root = document.documentElement;
  let theme = 'light';
  try { theme = localStorage.getItem(KEY) === 'dark' ? 'dark' : 'light'; } catch (_) { /* storage blocked */ }
  root.dataset.theme = theme;

  function label(button) {
    const light = root.dataset.theme === 'light';
    button.textContent = light ? '🌙 Lights Off' : '☀️ Lights On';
    button.title = light ? 'Switch lights off' : 'Switch lights on';
    button.setAttribute('aria-pressed', String(!light));
  }

  function initTheme() {
    const button = document.getElementById('theme-toggle');
    if (!button) return;
    label(button);
    button.addEventListener('click', () => {
      root.dataset.theme = root.dataset.theme === 'light' ? 'dark' : 'light';
      try { localStorage.setItem(KEY, root.dataset.theme); } catch (_) { /* storage blocked */ }
      label(button);
    });
  }

  // The menu button shows only below 1100px (each site's styles.css); this opens and closes it.
  function initNavToggle() {
    const button = document.getElementById('nav-toggle');
    const nav = document.getElementById('main-nav');
    if (!button || !nav) return;
    const set = open => { nav.classList.toggle('is-open', open); button.setAttribute('aria-expanded', String(open)); };
    button.addEventListener('click', e => { e.stopPropagation(); set(!nav.classList.contains('is-open')); });
    nav.addEventListener('click', e => { if (e.target.closest('a')) set(false); });
    document.addEventListener('click', e => { if (!e.target.closest('.site-header')) set(false); });
    document.addEventListener('keydown', e => { if (e.key === 'Escape') set(false); });
  }

  document.addEventListener('DOMContentLoaded', () => { initTheme(); initNavToggle(); });
})();
