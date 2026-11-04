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

  // A paper's code on the wall: LBD-569, or MIREX-m7.
  code: (uid) => (uid.startsWith('m') ? `MIREX-${uid}` : `LBD-${uid}`),

  // Time to go, as 02h 05m 33s, with days in front when there are any.
  countdown(seconds) {
    const pad = (value) => String(value).padStart(2, '0');
    const days = Math.floor(seconds / 86400);
    const clock = `${pad(Math.floor(seconds / 3600) % 24)}h ${pad(Math.floor(seconds / 60) % 60)}m ${pad(seconds % 60)}s`;
    return days ? `${days}d ${clock}` : clock;
  },

  duration(seconds) {
    const whole = Math.round(seconds);
    return `${Math.floor(whole / 60)}:${String(whole % 60).padStart(2, '0')}`;
  },

  // A warning for each time a paper's poster is up while its own video is on, on the screens wanted.
  async showConflicts(element, wanted = () => true) {
    const { timezone, conflicts } = await Kit.get('/api/conflicts');
    const found = conflicts.filter(wanted);
    element.innerHTML = found.length ? `<div class="notice"><b>Poster and video at the same time:</b><br>${found.map((c) =>
      `${Kit.code(c.uid)}: poster on ${c.poster_screen}, video on screen ${c.video_screen}, ` +
      `${Kit.clock(c.from_ms, timezone)}–${Kit.clock(c.to_ms, timezone)}`).join('<br>')}</div>` : '';
  },

  nav(active) {
    const pages = [['index.html', 'Links'], ['posters.html', 'Poster sessions'], ['lbd.html', 'LBD screens'],
      ['lbd-posters.html', 'LBD posters'], ['materials.html', 'Materials']];
    document.getElementById('nav').innerHTML = '<b>ISMIR 2026 onsite</b>' + pages.map(([href, label]) =>
      `<a href="${href}"${href === active ? ' class="active"' : ''}>${label}</a>`).join('');
    if (location.protocol === 'file:') {
      document.querySelector('main').insertAdjacentHTML('afterbegin',
        '<div class="notice">This page needs the kit: run python3 onsite-kit/serve.py, then open http://127.0.0.1:8765</div>');
    }
  },
};
