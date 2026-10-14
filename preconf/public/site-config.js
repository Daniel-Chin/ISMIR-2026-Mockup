// Backend location for this copy of the page. Empty = same origin (the Worker serves the page).
// scripts/build_miniconf.py overwrites this in the GitHub Pages build.
window.PC_CONFIG = window.PC_CONFIG || { apiOrigin: '', timeZone: 'Asia/Dubai' };
// The shared time-zone picker (vendor/timezone-preference.js) reads the venue zone from
// window.ISMIRSite, which the live overview sets in its site-integration.js.
window.ISMIRSite = window.ISMIRSite || { timeZone: window.PC_CONFIG.timeZone || 'Asia/Dubai' };
