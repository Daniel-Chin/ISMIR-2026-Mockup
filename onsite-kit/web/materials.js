Kit.nav('materials.html');
const $ = (id) => document.getElementById(id);
const LABELS = { paper: 'Paper', poster: 'Poster', video: 'Video', thumbnail: 'Thumbnail', captions: 'Captions', channel: 'Channel' };
const MARKS = { current: '✓', changed: '↻', missing: '↓', unknown: '?', local: '✓' };
const POLL_MS = 1000;
const selected = new Set();
let data;
let drawn = '';
let lastBytes = null;
let speed = 0;
let pollTimer;

const size = (bytes) => {
  if (bytes == null) return '';
  if (!bytes) return '0 MB';
  return bytes >= 1e9 ? `${(bytes / 1e9).toFixed(1)} GB` : `${Math.max(bytes / 1e6, 0.1).toFixed(1)} MB`;
};
const downloadable = (file) => file.size != null;
const needsUpdate = (file) => file.state === 'missing' || file.state === 'changed';
const eachFile = (rows, visit) => rows.forEach((row) => data.kinds.forEach((kind) => visit(row, kind, row.files[kind])));

function shownRows() {
  const search = $('search').value.trim().toLowerCase();
  return data.rows.filter((row) => (!search || row.uid.toLowerCase().includes(search) || row.title.toLowerCase().includes(search))
    && (!$('screen').value || row.screen === $('screen').value)
    && (!$('only-update').checked || data.kinds.some((kind) => needsUpdate(row.files[kind]))));
}

function cell(row, kind) {
  const file = row.files[kind];
  if (file.state === 'none') return '<td class="soft">–</td>';
  const key = `${row.uid}/${kind}`;
  const box = downloadable(file) ? `<input type="checkbox" data-key="${Kit.esc(key)}"${selected.has(key) ? ' checked' : ''}> ` : '';
  return `<td class="nowrap"><label>${box}<span class="${file.state}">${MARKS[file.state]}</span>
    <span class="soft">${size(file.size ?? file.local_size)}</span></label></td>`;
}

function drawTable() {
  const rows = shownRows();
  $('files').innerHTML = `<tr><th></th><th>uid</th><th>Screen</th><th>Title</th>${data.kinds.map((kind) =>
    `<th><button class="link" data-column="${kind}">${LABELS[kind]}</button></th>`).join('')}</tr>` +
    rows.map((row) => {
      const keys = data.kinds.filter((kind) => downloadable(row.files[kind])).map((kind) => `${row.uid}/${kind}`);
      const all = keys.length && keys.every((key) => selected.has(key));
      return `<tr><td><input type="checkbox" data-row="${Kit.esc(row.uid)}"${all ? ' checked' : ''}></td>
        <td class="nowrap">${Kit.esc(row.uid)}</td><td>${Kit.esc(row.screen)}</td>
        <td class="title">${Kit.esc(row.title)}</td>${data.kinds.map((kind) => cell(row, kind)).join('')}</tr>`;
    }).join('');
}

function drawSelection() {
  let bytes = 0;
  eachFile(data.rows, (row, kind, file) => { if (selected.has(`${row.uid}/${kind}`)) bytes += file.size || 0; });
  $('selected').textContent = `${selected.size} files selected, ${size(bytes)}`;
  $('download').disabled = !selected.size || Boolean(data.job.running);
}

function drawSummary() {
  const count = { current: 0, changed: 0, missing: 0 };
  let onDisk = 0;
  eachFile(data.rows, (row, kind, file) => {
    if (file.state in count) count[file.state] += 1;
    onDisk += file.local_size || 0;
  });
  const when = data.checked_ms ? new Date(data.checked_ms).toLocaleString() : 'never';
  $('summary').innerHTML = `<span class="current">${count.current} up to date</span> ·
    <span class="changed">${count.changed} changed</span> ·
    <span class="missing">${count.missing} not downloaded</span> ·
    ${size(onDisk)} on this MacBook · checked: ${Kit.esc(when)}`;
}

function drawJob() {
  const job = data.job;
  const failures = (job.failed || []).length ? `${job.failed.length} failed:<br>${job.failed.map(Kit.esc).join('<br>')}` : '';
  $('job').hidden = !job.action;
  $('cancel').hidden = !(job.running && job.action === 'download');
  $('check').disabled = Boolean(job.running);
  $('failed').innerHTML = job.error ? Kit.esc(job.error) : failures;
  if (job.action === 'check') {
    $('meter').style.width = job.total ? `${(100 * job.done) / job.total}%` : '0';
    $('job-text').textContent = job.running ? `Checking Drive: ${job.done}/${job.total}` : 'Check finished';
  } else if (job.action === 'download') {
    if (lastBytes !== null) speed = 0.7 * speed + 0.3 * Math.max(job.done_bytes - lastBytes, 0) * (1000 / POLL_MS);
    lastBytes = job.running ? job.done_bytes : null;
    const left = speed > 0 ? ` · about ${Kit.duration((job.total_bytes - job.done_bytes) / speed)} left` : '';
    $('meter').style.width = job.total_bytes ? `${(100 * job.done_bytes) / job.total_bytes}%` : '0';
    $('job-text').textContent = job.running
      ? `${job.files_done}/${job.files} files · ${size(job.done_bytes)} of ${size(job.total_bytes)} · ${size(speed)}/s${left} · ${job.active.join(', ')}`
      : `Downloaded ${job.files_done} of ${job.files} files`;
  }
}

async function poll() {
  clearTimeout(pollTimer);
  data = await Kit.get('/api/materials').catch(() => data);
  if (!data.configured) {
    $('notice').innerHTML = '<div class="notice">No DRIVE_FOLDER_* lines in .onsite_env: see README.md.</div>';
  } else if (data.unmatched.length) {
    $('notice').innerHTML = `<div class="notice">Drive folders with no LBD in .onsite_env, skipped: ${data.unmatched.map(Kit.esc).join(', ')}. Rerun make_env.py.</div>`;
  } else {
    $('notice').innerHTML = '';
  }
  const fingerprint = JSON.stringify(data.rows) + data.checked_ms;
  if (fingerprint !== drawn) {
    drawn = fingerprint;
    drawTable();
    drawSummary();
  }
  drawSelection();
  drawJob();
  pollTimer = setTimeout(poll, data.job.running ? POLL_MS : 3000);
}

async function act(body) {
  try {
    await Kit.post('/api/materials', body);
    $('notice').innerHTML = '';
    await poll();
  } catch (error) {
    $('notice').innerHTML = `<div class="notice">${Kit.esc(error.message)}</div>`;
  }
}

function setMany(rows, wanted) {
  eachFile(rows, (row, kind, file) => {
    const key = `${row.uid}/${kind}`;
    if (downloadable(file) && wanted(kind, file)) selected.add(key);
  });
  drawTable();
  drawSelection();
}

function toggle(key, on) {
  if (on) selected.add(key);
  else selected.delete(key);
}

$('files').addEventListener('change', (event) => {
  const { key, row: uid } = event.target.dataset;
  if (key) toggle(key, event.target.checked);
  if (uid) {
    const row = data.rows.find((candidate) => candidate.uid === uid);
    data.kinds.filter((kind) => downloadable(row.files[kind]))
      .forEach((kind) => toggle(`${uid}/${kind}`, event.target.checked));
  }
  drawTable();
  drawSelection();
});
$('files').addEventListener('click', (event) => {
  const kind = event.target.dataset.column;
  if (!kind) return;
  const rows = shownRows().filter((row) => downloadable(row.files[kind]));
  const on = !rows.every((row) => selected.has(`${row.uid}/${kind}`));
  rows.forEach((row) => toggle(`${row.uid}/${kind}`, on));
  drawTable();
  drawSelection();
});
$('select-update').onclick = () => { setMany(data.rows, (kind, file) => needsUpdate(file)); };
$('select-all').onclick = () => setMany(shownRows(), () => true);
$('select-none').onclick = () => { selected.clear(); drawTable(); drawSelection(); };
['search', 'screen', 'only-update'].forEach((id) => { $(id).oninput = drawTable; });
$('check').onclick = () => act({ action: 'check' });
$('cancel').onclick = () => act({ action: 'cancel' });
$('download').onclick = async () => {
  speed = 0;
  lastBytes = null;
  const files = [...selected];
  selected.clear();
  drawTable();
  await act({ action: 'download', files });
};

$('screen').innerHTML += ['1', '2', '3', '4', '5', '6', '7'].map((id) => `<option>${id}</option>`).join('');
poll().then(() => { if (data.configured && !data.checked_ms && !data.job.running) act({ action: 'check' }); });
