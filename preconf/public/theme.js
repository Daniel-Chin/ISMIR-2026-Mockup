// Loaded synchronously in <head> so the page never flashes the wrong theme.
// Same key and button labels as the live overview.
(function () {
  var KEY = 'ismirColorTheme';
  var root = document.documentElement;
  var theme = 'light';
  try { theme = localStorage.getItem(KEY) === 'dark' ? 'dark' : 'light'; } catch (e) { /* storage blocked */ }
  root.dataset.theme = theme;

  function label(button) {
    var light = root.dataset.theme === 'light';
    button.textContent = light ? '🌙 Lights Off' : '☀️ Lights On';
    button.setAttribute('aria-pressed', String(!light));
  }
  document.addEventListener('DOMContentLoaded', function () {
    var button = document.getElementById('theme-toggle');
    if (!button) return;
    label(button);
    button.addEventListener('click', function () {
      root.dataset.theme = root.dataset.theme === 'light' ? 'dark' : 'light';
      try { localStorage.setItem(KEY, root.dataset.theme); } catch (e) { /* storage blocked */ }
      label(button);
    });
  });
})();
