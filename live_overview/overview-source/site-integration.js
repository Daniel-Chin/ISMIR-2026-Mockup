/* Miniconf integration: conference info comes from sitedata config.yml (frozen into
   public-site-config.js at build time); backend state is never altered, only how it is shown. */
(function () {
  'use strict';
  const conf = window.ISMIR_PUBLIC_CONFIG?.conference || {};
  const programSite = String(conf.miniconfUrl).replace(/\/+$/, '');

  // Never show a raw Zoom URL: an event's Zoom button goes through the miniconf redirect page.
  function zoomRedirectUrl(event) {
    const uid = String(event.sourceEventId || String(event.id || '').replace(/^event-/, ''));
    return `${programSite}/zoom.html?event_uid=${encodeURIComponent(uid)}`;
  }

  function isZoomRedirectUrl(url) {
    const base = new URL(programSite + '/zoom.html');
    return url.origin === base.origin && url.pathname === base.pathname;
  }

  function localizeState(state) {
    for (const event of state?.events || []) {
      if (event.links?.zoom) event.links.zoom = zoomRedirectUrl(event);
      for (const paper of event.papers || []) if (paper.links) delete paper.links.zoom;
    }
    return state;
  }

  function applyConferenceText(root = document) {
    const values = { name: conf.name, date: conf.date };
    root.querySelectorAll('[data-conf]').forEach((node) => {
      const value = values[node.dataset.conf];
      if (value) node.textContent = value;
    });
    if (conf.name) document.title = `${conf.name} ${document.title}`;
    // The page stands alone (no miniconf wrapper), so its own nav links back to the configured miniconf.
    const links = { miniconf: programSite + '/', official: conf.officialSiteUrl };
    root.querySelectorAll('[data-site-link]').forEach((node) => {
      const href = links[node.dataset.siteLink];
      if (href) node.setAttribute('href', href);
    });
  }

  window.ISMIRSite = {
    conference: conf,
    programSite,
    timeZone: conf.timezone,
    zoomRedirectUrl,
    isZoomRedirectUrl,
    localizeState,
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', () => applyConferenceText());
  else applyConferenceText();
})();
