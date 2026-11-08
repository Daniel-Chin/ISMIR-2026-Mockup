"""Plain-text conference reference for chat AIs, published at {prefix}/live_overview/llm/.

The "Copy prompt" buttons (app.js, history.js) copy a short prompt: the time, what is live and
the live numbers, plus links to these files. Chat AIs cannot run the Live Overview's scripts, but
they can read plain text, so the programme lives here and they open only what a question needs.

  index.txt          how to read the files, links, the full schedule
  papers.txt         every paper, one line each: ID, title, authors, topics, its session file
  session-N.txt      paper session N (oral N and poster N): every paper with its abstract

Only public links are written: Slack channels, livestreams, miniconf pages and the miniconf's
Zoom redirect page (zoom.html), never a raw Zoom link. Times are the conference's local time.
"""
from datetime import datetime

DIR = 'llm'


def _when(iso):
    return datetime.fromisoformat(iso)


def _day(iso):   # "Mon Nov 9"
    when = _when(iso)
    return f'{when:%a %b} {when.day}'


def _hm(iso):
    return _when(iso).strftime('%H:%M')


def _offset(iso):
    raw = _when(iso).strftime('%z')   # +0400
    return f'UTC{raw[:3]}:{raw[3:]}' if raw else 'UTC'


def _text(value):
    text = ' '.join(str(value or '').split())
    return '' if text.lower() in ('na', 'n/a', 'none', '-', 'tba', 'tbd') else text   # sheet placeholders


def _links(pairs):
    # Sheets hold placeholders such as "NA" or "Confidential" where there is no link.
    return ' · '.join(f'{label}: {url}' for label, url in pairs if str(url or '').startswith(('https://', 'http://')))


def _topics(paper):
    leaves = [str(s).split('->')[-1].strip() for s in paper.get('subjects') or []]
    return '; '.join(dict.fromkeys(x for x in leaves if x))


def _mode(paper):
    mode = str(paper.get('presenterMode') or '').lower()
    return {'online': 'virtual', 'mixed': 'in-person + virtual'}.get(mode, 'in-person' if mode else 'mode TBA')


def _zoom_page(conf, event):
    if not (event.get('links') or {}).get('zoom'):
        return ''
    uid = str(event.get('sourceEventId') or str(event.get('id', '')).removeprefix('event-'))
    return f"{conf['miniconf_url']}/zoom.html?event_uid={uid}"


def _room(event):
    room = _text(event.get('venue'))
    return f' · Room: {room}' if room else ''


def _event_links(conf, event):
    links = event.get('links') or {}
    return _links([('Slack', links.get('slack')), ('Zoom', _zoom_page(conf, event)),
                   ('Livestream', links.get('youtube')), ('Info', event.get('detailUrl'))])


def _paper_sessions(events):
    """sessionNumber -> (events presenting that session's papers, the papers)."""
    sessions = {}
    for e in events:
        if not e.get('papers'):
            continue
        n = e.get('sessionNumber')
        events_, papers = sessions.setdefault(n, ([], {}))
        events_.append(e)
        for p in e['papers']:
            papers.setdefault(p.get('sourcePaperId') or p['id'], p)
    return dict(sorted(sessions.items(), key=lambda kv: (kv[0] is None, kv[0] or 0)))


def _session_name(n):
    return f'session-{n}.txt'


def build(schedule, conf):
    """{file name: text} for the llm/ directory."""
    events = sorted((e for e in schedule.get('events', []) if not e.get('debugOnly')), key=lambda e: (e['startsAt'], e['id']))
    base = f"{conf['miniconf_url']}/live_overview/{DIR}/"
    tz = schedule.get('conference', {}).get('timeZone') or conf['timezone']
    offset = _offset(events[0]['startsAt']) if events else 'UTC'
    sessions = _paper_sessions(events)
    files = {}

    out = [f"# {conf['name']} reference for AI assistants",
           f"{conf['name']} is the conference of the International Society for Music Information Retrieval (ISMIR), {conf['date']}.",
           f'All times in these files are conference local time: {tz} ({offset}).',
           'Live status (what is on right now, Zoom headcounts) is not in these files; it comes from the prompt copied from the Live Overview page.',
           '',
           '## How to read this',
           '- Oral Session N and Poster Session N present the same papers: short talks first, then the poster session where you talk to the authors (on-site posters, plus one Zoom room per poster for online participants).',
           f'- All papers, one line each (title, authors, topics, when): {base}papers.txt',
           f"- Paper IDs like P3-07 mean paper session 3, paper 7. Abstracts of session N, with each paper's Slack channel and page: {base}session-N.txt",
           '- Every session and every paper has its own Slack channel in the conference Slack workspace, for questions and discussion with the authors, also after the session.',
           '- "Zoom" links go to the program site, which sends signed-in attendees to the meeting.',
           '- "Room" is where an event takes place on-site (NYU Abu Dhabi campus); events without one have no on-site room listed.',
           '',
           '## Links',
           f"- Live overview (now and next): {conf['miniconf_url']}/live.html",
           f"- Program site (papers, schedule, posters): {conf['miniconf_url']}/"]
    if conf.get('helpdesk_url'):
        out.append(f"- Helpdesk Slack channel (logistics problems): {conf['helpdesk_url']}")
    if conf.get('official_site_url'):
        out.append(f"- Official conference website: {conf['official_site_url']}")

    out += ['', f'## Schedule ({tz})']
    day = ''
    for e in events:
        if _day(e['startsAt']) != day:
            day = _day(e['startsAt'])
            out.append(f'### {day}')
        end = 'TBD' if e.get('endTimeTBD') else _hm(e['endsAt'])
        line = f"- {_hm(e['startsAt'])}–{end} {e['title']} ({e.get('category') or e.get('type')})" + _room(e)
        extra = [_text(e.get('organiser')) and f"organiser: {_text(e['organiser'])}", _text(e.get('summary'))]
        line += ''.join(f' · {x}' for x in extra if x)
        links = _event_links(conf, e)
        out.append(line + (f' · {links}' if links else ''))

    files['index.txt'] = '\n'.join(out) + '\n'

    out = [f"# {conf['name']} papers",
           f'Times: {tz} ({offset}). Abstracts, Slack channels and paper pages: the session file named in each heading.']
    for n, (evs, papers) in sessions.items():
        when = ', '.join(f"{e['title']} {_day(e['startsAt'])} {_hm(e['startsAt'])}" for e in evs)
        out += ['', f'## Session {n}: {when} · {base}{_session_name(n)}']
        for p in papers.values():
            topics = _topics(p)
            out.append(f"- {p.get('displayId') or p['id']} \"{_text(p['title'])}\" — {_text(p.get('authors'))}" + (f' · {topics}' if topics else ''))
    files['papers.txt'] = '\n'.join(out) + '\n'

    for n, (evs, papers) in sessions.items():
        out = [f"# {conf['name']} paper session {n}", f'Times: {tz} ({offset}). Schedule and other sessions: {base}index.txt', '']
        for e in evs:
            end = 'TBD' if e.get('endTimeTBD') else _hm(e['endsAt'])
            links = _event_links(conf, e)
            out.append(f"- {e['title']}: {_day(e['startsAt'])} {_hm(e['startsAt'])}–{end}" + _room(e) + (f' · {links}' if links else ''))
        for p in papers.values():
            links = p.get('links') or {}
            out += ['', f"## {p.get('displayId') or p['id']} {_text(p['title'])}",
                    f"Authors: {_text(p.get('authors'))} · presented {_mode(p)}"]
            if _topics(p):
                out.append(f'Topics: {_topics(p)}')
            page = _links([('Slack', links.get('slack')), ('Page (PDF, poster, video)', p.get('detailUrl'))])
            if page:
                out.append(page)
            for label, key in (('Abstract', 'abstract'), ('Fun fact', 'funFact')):
                if _text(p.get(key)):
                    out.append(f'{label}: {_text(p[key])}')
        files[_session_name(n)] = '\n'.join(out) + '\n'
    return files
