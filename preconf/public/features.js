'use strict';
/*
 * Features under test, and the page's channel. A classic script, loaded before app.js.
 *
 * lounge.html and lounge-debug.html are built from the same index.html and run the same code; the
 * build only marks lounge-debug.html with <html data-channel="debug"> (build_miniconf.py
 * debug_page). On that page every feature below is on, whatever its stage. Shipping a feature to
 * lounge.html = changing its stage from 'debug' to 'live' here. Code asks pcFeature('name'); an
 * unknown name throws. The same scheme as the Live Overview's features.js.
 */
(function () {
  const FEATURES = Object.freeze({
    industryBoard: 'live',    // the Industry Board below the LBDs: sponsor logos and the CV pool
  });
  const channel = document.documentElement.dataset.channel === 'debug' ? 'debug' : 'live';
  window.PC_CHANNEL = channel;
  window.pcFeature = (name) => {
    const stage = FEATURES[name];
    if (stage !== 'debug' && stage !== 'live') throw new Error(`Unknown feature: ${name}`);
    return stage === 'live' || channel === 'debug';
  };
  if (channel !== 'debug') return;

  // A banner on the debug page, so it is never mistaken for the public one.
  const banner = () => {
    const testing = Object.keys(FEATURES).filter(name => FEATURES[name] === 'debug');
    const box = document.createElement('div');
    box.className = 'pc-debug-banner';
    box.setAttribute('role', 'note');
    box.innerHTML = '<strong>DEBUG PAGE</strong> <span>Testing: ' + (testing.length ? testing.join(', ') : 'nothing')
      + '</span> <a href="lounge.html">Public page →</a>';
    document.body.prepend(box);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', banner);
  else banner();
})();
