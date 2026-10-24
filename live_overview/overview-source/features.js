'use strict';
/*
 * Features under test, and the page's channel. Loaded first, before every other script.
 *
 * live.html and live-debug.html are built from the same index.html and run the same code; the
 * build only marks live-debug.html with <html data-channel="debug">. On that page:
 *   - every feature below is on, whatever its stage;
 *   - the organisers' test clock (admin.html) applies. live.html always shows real time.
 *
 * Shipping a feature to live.html = changing its stage from 'debug' to 'live' here. Nothing is
 * copied between pages, so nothing can be left behind. Code asks ismirFeature('name'); an
 * unknown name throws, and test/features.test.cjs checks that every name asked for is listed
 * here and every listed feature is still used.
 */
(function () {
  const FEATURES = Object.freeze({
    // name: 'debug' | 'live', e.g. newPanel: 'debug'. Nothing is under test right now.
  });
  const channel = document.documentElement.dataset.channel === 'debug' ? 'debug' : 'live';
  window.ISMIRChannel = channel;
  window.ISMIR_FEATURES = FEATURES;
  window.ismirFeature = (name) => {
    const stage = FEATURES[name];
    if (stage !== 'debug' && stage !== 'live') throw new Error(`Unknown feature: ${name}`);
    return stage === 'live' || channel === 'debug';
  };
  if (channel !== 'debug') return;

  // A banner on every debug page, so it is never mistaken for the public one.
  const banner = () => {
    const testing = Object.keys(FEATURES).filter(name => FEATURES[name] === 'debug');
    const box = document.createElement('div');
    box.className = 'debug-channel-banner';
    box.setAttribute('role', 'note');
    box.innerHTML = '<strong>DEBUG PAGE</strong> <span data-debug-clock>Real time</span>'
      + ` <span class="debug-channel-features">Testing: ${testing.length ? testing.join(', ') : 'nothing'}</span>`
      + ' <a href="live.html">Public page →</a>';
    document.body.prepend(box);
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', banner);
  else banner();
})();
