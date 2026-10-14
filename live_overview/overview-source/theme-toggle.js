(function () {
  const KEY = "ismirColorTheme";
  const root = document.documentElement;

  function getStoredTheme() {
    try {
      const stored = localStorage.getItem(KEY);
      return stored === "dark" ? "dark" : "light";
    } catch (error) {
      return root.dataset.theme === "dark" ? "dark" : "light";
    }
  }

  function setTheme(theme) {
    const next = theme === "light" ? "light" : "dark";
    root.dataset.theme = next;
    try {
      localStorage.setItem(KEY, next);
    } catch (error) {
      // localStorage can be unavailable in restricted embedded contexts.
    }
    updateButtons(next);
  }

  function updateButtons(theme) {
    document.querySelectorAll("#theme-toggle, [data-theme-toggle]").forEach((button) => {
      button.textContent = theme === "light" ? "🌙 Lights Off" : "☀️ Lights On";
      button.setAttribute("aria-pressed", String(theme === "light"));
      button.title = theme === "light" ? "Switch lights off" : "Switch lights on";
    });
  }

  setTheme(getStoredTheme());

  // Below 1100px (narrow windows, or a zoomed-in browser) the nav sits behind a menu
  // button (styles.css "collapsible nav"); this opens and closes it.
  function initNavToggle() {
    const button = document.getElementById("nav-toggle");
    const nav = document.getElementById("main-nav");
    if (!button || !nav) return;
    const set = (open) => { nav.classList.toggle("is-open", open); button.setAttribute("aria-expanded", String(open)); };
    button.addEventListener("click", (event) => { event.stopPropagation(); set(!nav.classList.contains("is-open")); });
    nav.addEventListener("click", (event) => { if (event.target.closest("a")) set(false); });
    document.addEventListener("click", (event) => { if (!event.target.closest(".site-header")) set(false); });
    document.addEventListener("keydown", (event) => { if (event.key === "Escape") set(false); });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initNavToggle();
    updateButtons(root.dataset.theme || getStoredTheme());
    document.querySelectorAll("#theme-toggle, [data-theme-toggle]").forEach((button) => {
      button.addEventListener("click", () => {
        setTheme(root.dataset.theme === "light" ? "dark" : "light");
      });
    });
  });
})();
