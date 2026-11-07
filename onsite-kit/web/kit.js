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

  // What the Live Database, as last read, would change in the LBD screens' plan, with a button to take it.
  async showPlan(element) {
    const status = await Kit.get('/api/lbd-plan');
    const problems = status.problems.length
      ? `<p class="warn">Not planned: ${status.problems.map(Kit.esc).join('; ')}</p>` : '';
    if (!status.changes.length) {
      element.innerHTML = `<p class="soft">The screens follow the Live Database as read ${status.read_ms
        ? Kit.clock(status.read_ms, status.timezone, true) : 'never'}.</p>${problems}`;
      return;
    }
    element.innerHTML = `<div class="notice"><b>The Live Database changes the LBD screens:</b><br>
      ${status.changes.map(Kit.esc).join('<br>')}${problems}
      <p>Every MacBook works out the same plan. A screen playing now jumps to the new plan; a changed screen
        loses its edits in Manage, but keeps its start time.</p>
      <button class="primary" id="apply-plan">Update the screens</button></div>`;
    element.querySelector('#apply-plan').onclick = async (event) => {
      event.target.disabled = true;
      event.target.textContent = 'Reading the Live Database…';
      try {
        const done = await Kit.post('/api/lbd-plan', {});
        if (done.reset.length) alert(`Edits in Manage replaced on: ${done.reset.join(', ')}`);
        location.reload();
      } catch (error) {
        event.target.disabled = false;
        event.target.textContent = 'Update the screens';
        element.insertAdjacentHTML('beforeend', `<p class="warn">${Kit.esc(error.message)}</p>`);
      }
    };
  },

  // When this MacBook last read the Live Database; everything but the media comes from that reading.
  async liveStatus(failed) {
    const button = document.getElementById('live');
    const live = await Kit.get('/api/live').catch(() => null);
    if (!button || !live) return;
    const error = failed || live.error;
    button.classList.toggle('warn', Boolean(error) || !live.read_ms);
    button.title = error ? `${error}\nClick to try again` : 'Read the Live Database again';
    button.textContent = !live.configured ? 'Live Database: no links in .onsite_env'
      : live.read_ms ? `Live Database: ${Kit.clock(live.read_ms, live.timezone, true)} ↻` : 'Live Database: not read yet ↻';
  },

  nav(active) {
    const pages = [['index.html', 'Links'], ['posters.html', 'Poster sessions'], ['talks.html', 'Talk sessions'],
      ['lbd.html', 'LBD screens'], ['lbd-posters.html', 'LBD posters'], ['materials.html', 'Materials'],
      ['paper-materials.html', 'Paper materials']];
    document.getElementById('nav').innerHTML = '<b>ISMIR 2026 onsite</b>' + pages.map(([href, label]) =>
      `<a href="${href}"${href === active ? ' class="active"' : ''}>${label}</a>`).join('') +
      '<button class="live" id="live" title="Read the Live Database again">Live Database</button>';
    Kit.liveStatus();
    document.getElementById('live').onclick = async () => {
      const button = document.getElementById('live');
      button.disabled = true;
      button.textContent = 'Reading the Live Database…';
      try {
        await Kit.post('/api/live', {});
        location.reload();
      } catch (error) {
        button.disabled = false;
        Kit.liveStatus(error.message);
      }
    };
    if (location.protocol === 'file:') {
      document.querySelector('main').insertAdjacentHTML('afterbegin',
        '<div class="notice">This page needs the kit: run python3 onsite-kit/serve.py, then open http://127.0.0.1:8765</div>');
    }
  },
};
