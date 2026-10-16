/* Prompt wording is owned by llm-prompts.json; fetch a fresh copy on every click. */
(function () {
  'use strict';
  const configUrl = new URL('./llm-prompts.json', document.currentScript.src);
  window.ISMIRPrompts = {
    async build(kind, snapshot) {
      const url = new URL(configUrl);
      url.searchParams.set('_', String(Date.now()));
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 8000);
      try {
        const response = await fetch(url, { cache: 'no-store', signal: controller.signal });
        if (!response.ok) throw new Error('Prompt configuration unavailable.');
        const config = await response.json();
        const paragraphs = config[kind]?.paragraphs;
        if (config.version !== 1 || !Array.isArray(paragraphs) || !paragraphs.length ||
            paragraphs.some(p => typeof p !== 'string') || !paragraphs.join('').trim()) {
          throw new Error('Invalid prompt configuration.');
        }
        const values = {
          conferenceName: window.ISMIRSite?.conference?.name || snapshot?.conference?.name || 'the conference',
          // Inside miniconf the shareable page is {prefix}/live.html, not this asset dir.
          pageUrl: window.ISMIRSite?.conference?.miniconfUrl
            ? (kind === 'history' ? new URL('./history.html', configUrl).href : window.ISMIRSite.programSite + '/live.html')
            : new URL(kind === 'history' ? './history.html' : './', configUrl).href,
          snapshot: JSON.stringify(snapshot, null, 2)
        };
        return paragraphs.join('\n\n').replace(/\{\{(\w+)\}\}/g, (match, key) => {
          if (!Object.hasOwn(values, key)) throw new Error('Unknown prompt placeholder: ' + key);
          return values[key];
        });
      } finally { clearTimeout(timer); }
    }
  };
})();
