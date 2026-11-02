// Shared by every page.
const Kit = {
  esc: (text) => String(text ?? '').replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`),

  async get(url) {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${url}: ${response.status}`);
    return response.json();
  },

  async post(url, body) {
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || response.status);
    return data;
  },

  clock: (ms, timeZone, withDay) => new Intl.DateTimeFormat('en-GB', {
    timeZone,
    hour: '2-digit',
    minute: '2-digit',
    ...(withDay ? { weekday: 'short', day: 'numeric', month: 'short' } : {}),
  }).format(ms),

  duration(seconds) {
    const whole = Math.round(seconds);
    return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
  },

  nav(active) {
    const pages = [['index.html', 'Links'], ['posters.html', 'Poster sessions'], ['lbd.html', 'LBD screens'], ['materials.html', 'Materials']];
    document.getElementById('nav').innerHTML = '<b>ISMIR 2026 onsite</b>' + pages.map(([href, label]) =>
      `<a href="${href}"${href === active ? ' class="active"' : ''}>${label}</a>`).join('');
    if (location.protocol === 'file:') {
      document.querySelector('main').insertAdjacentHTML('afterbegin',
        '<div class="notice">This page needs the kit: run python3 onsit-kit/serve.py, then open http://127.0.0.1:8765</div>');
    }
  },
};
