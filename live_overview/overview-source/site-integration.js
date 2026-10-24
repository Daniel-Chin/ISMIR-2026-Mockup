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

  // extra-events.json "zoomDirect": the backend sends the meeting link without its passcode (the
  // full link is in the event's Slack channel). Kept as is, but only a passcode-free Zoom link.
  function directZoomUrl(link) {
    try {
      const url = new URL(link);
      if (url.protocol !== 'https:' || !/(^|\.)(zoom\.us|zoom\.com|zoomgov\.com)$/.test(url.hostname)) return '';
      url.search = ''; url.hash = '';
      return url.href;
    } catch (_) { return ''; }
  }

  function localizeState(state) {
    for (const event of state?.events || []) {
      if (event.links?.zoom) event.links.zoom = (event.zoomDirect && directZoomUrl(event.links.zoom)) || zoomRedirectUrl(event);
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
    // The Warm-up Discussion is the miniconf's other add-on, at {prefix}/lounge.html (preconf/).
    const links = { miniconf: programSite + '/', warmup: programSite + '/lounge.html', official: conf.officialSiteUrl };
    root.querySelectorAll('[data-site-link]').forEach((node) => {
      const href = links[node.dataset.siteLink];
      if (href) node.setAttribute('href', href);
    });
  }

  /**
   * The server's clock. Every time these pages show or decide on (what is live, the test clock on
   * live-debug.html, "today") is read from it, never from this computer's clock, which may be set
   * wrong. Each answer from the backend (public-connection.js) sets the offset; until the first,
   * this computer's clock stands in.
   */
  const clock = {
    offset: 0,
    synced: false,
    now() { return Date.now() + this.offset; },
    /** The server said `serverMs` at about `localMs` (this computer's clock then). */
    sync(serverMs, localMs = Date.now()) {
      if (!Number.isFinite(serverMs) || !Number.isFinite(localMs)) return;
      this.offset = serverMs - localMs;
      this.synced = true;
    },
  };
  window.ISMIRClock = clock;

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
