"""Everything the kit shows from the Live Database, read on this MacBook. Python standard library only.

.onsite_env holds only the links to the sheet tabs (SHEET_*). The tabs are read when the server starts and when
asked, all of each tab, so a new column needs no new .onsite_env; the last reading is kept in .state/ for when
there is no network.
"""

from __future__ import annotations

import csv
import io
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import materials

# The tabs, as SHEET_<name> in .onsite_env, and how the Links page names them.
SHEETS = {
    'PAPERS': ('Papers', 'Paper metadata, media links'),
    'EVENTS': ('Events', "The schedule; each event's Zoom, Slack and room"),
    'SESSION_ASSIGNMENT': ('Session assignment', 'Which paper is in which session'),
    'LBDS': ('LBDs', 'LBD and MIREX metadata, media links'),
    'LBD_GROUPS': ('LBD groups', 'LBD topics and their Slack channels'),
    'ORAL_SESSIONS': ('Oral sessions', 'Order, chairs, presenters, onsite or remote, slides; see Talk sessions'),
    'AWARD_SESSIONS': ('Award sessions', 'Order, chairs, presenters, onsite or remote, slides; see Talk sessions'),
}
READ = ('PAPERS', 'EVENTS', 'LBDS', 'LBD_GROUPS', 'ORAL_SESSIONS', 'AWARD_SESSIONS')  # the others are links only
GITHUB = 'https://github.com/Daniel-Chin/ISMIR2026-Kit'
EMPTY = {'read_ms': 0, 'timezone': 'UTC', 'lbd_start': '', 'lbd_end': '', 'shared_zoom': '', 'poster_sessions': [],
         'lbds': [], 'groups': {}, 'group_slack': {}, 'sessions': [], 'talks': {}}


def sheet_rows(link: str) -> list:
    """A sheet tab, by the link to it, with its column names plain: '🔒 CMT ID' -> 'cmt id'."""
    found = re.search(r'/spreadsheets/d/([\w-]+).*?[#?&]gid=(\d+)', link)
    if not found:
        raise RuntimeError(f'not a link to a sheet tab: {link[:60]}')
    text = materials.curl(f'https://docs.google.com/spreadsheets/d/{found[1]}/export?format=csv&gid={found[2]}')
    return [{key.replace('🔒', '').strip().lower(): mended((value or '').strip()) for key, value in row.items() if key}
            for row in csv.DictReader(io.StringIO(text))]


def mended(text: str) -> str:
    """Text pasted into the sheet as UTF-8 read as Latin-1 ('JosÃ©'), back as it was ('José')."""
    if 'Ã' not in text and 'Â' not in text:
        return text
    try:
        return text.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text


def site_config(path: Path) -> dict:
    """The plain 'key: value' lines of the website's config.yml (in the repo), without a YAML library."""
    found = {}
    if path.exists():
        for key, value in re.findall(r'^(\w+):[ \t]*(.*?)[ \t]*$', path.read_text(encoding='utf-8'), re.M):
            found[key] = value.strip('\'"')
    return found


def people(text: str) -> list:
    """'Ann Lee (KAIST; NYU)*; Bo Li (NYU)' -> [['Ann Lee', ['KAIST', 'NYU']], ['Bo Li', ['NYU']]].

    Authors are split on the semicolons outside parentheses; * marks the contact author.
    """
    found = []
    for part in filter(None, (piece.strip() for piece in re.split(r';(?![^(]*\))', text))):
        match = re.fullmatch(r'([^(]*?)\s*\((.*)\)\s*\**', part)
        if match:
            found.append([match[1].strip(), [place.strip() for place in match[2].split(';') if place.strip()]])
        else:
            found.append([part.rstrip('*').strip(), []])
    return found


def venue_zone(name: str):
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def iso_time(day: str, clock: str, zone) -> str:
    return datetime.strptime(f'{day} {clock}', '%Y-%m-%d %H:%M').replace(tzinfo=zone).isoformat()


def lbd_rows(rows: list) -> list:
    """The LBDs and MIREX entries, with the Drive ids of their files: a MIREX folder, named after its task, is
    found through them."""
    return [{
        'uid': r['uid'],
        'title': r.get('title', ''),
        # From the parsed people, as affiliations can hold parentheses of their own: (... (UIUC)).
        'authors': '; '.join(name for name, _ in people(r.get('authors_and_affil_from_pdf', ''))),
        'people': people(r.get('authors_and_affil_from_pdf', '')),
        'mode': r.get('presentation_mode', ''),
        'ok': r.get('ok_to_present', '') or 'Yes',  # No: not on the screens
        'group': r.get('group_id', ''),
        'slack': r.get('slack_channel', ''),
        'file_ids': sorted({source[0] for key in ('raw_pdf_path', 'raw_poster_pdf', 'raw_video_path', 'raw_thumbnail_path')
                            for source in [materials.link_source(r.get(key, ''))] if source}),
    } for r in rows if r.get('uid')]


def poster_sessions(events: list, site: str, zone) -> list:
    return [{
        'title': e['title'],
        'start': iso_time(e['start_date'], e['start_time'], zone),
        'end': iso_time(e['start_date'], e['end_time'], zone),
        'location': e.get('onsite_location', ''),
        'zoom': e.get('live_url', ''),
        'slack': e.get('channel_url', ''),
        'miniconf': f'{site}/papers.html?session={e["title"].split()[-1]}&type=poster',
    } for e in events if e.get('category') == 'Poster session']


def talk_sessions(events: list, papers: list, oral: list, award: list, zone):
    """The oral and award sessions, each with its papers in order; and every paper's title, authors and files.

    A paper's files are links from the sheets: its PDF (Papers), and its slides for each session as PDF.
    """
    by_uid = {row.get('uid', ''): row for row in papers}
    times = {}
    for event in events:
        number = re.search(r'Oral Session - (\d+)', event.get('title', ''))
        if number and event.get('category') in ('Oral session', 'Award nominee'):
            times[('A' if event['category'] == 'Award nominee' else 'O') + number[1]] = event
    sessions, talks = {}, {}
    for key_of, rows, prefix in ((lambda r: 'O' + r['session_index'], oral, ''),
                                 (lambda r: r['award_session_index'], award, 'award_')):
        for row in rows:
            if not row.get('cmt id'):
                continue
            key, uid = key_of(row), row['cmt id']
            event = times.get(key, {})
            session = sessions.setdefault(key, {
                'key': key, 'kind': 'award' if prefix else 'oral',
                'title': ' · '.join(event.get('title', key).split('\n')),
                'start': iso_time(event['start_date'], event['start_time'], zone) if event else '',
                'end': iso_time(event['start_date'], event['end_time'], zone) if event else '',
                'location': event.get('onsite_location', ''),
                'chair_onsite': row.get('chair_onsite', ''), 'chair_remote': row.get('chair_remote', ''), 'papers': []})
            session['papers'].append({'uid': uid, 'position': int(row.get('position_in_session') or 0),
                                      'presenter': row.get('presenter', ''), 'modality': row.get('modality', '')})
            paper = by_uid.get(uid, {})
            talk = talks.setdefault(uid, {
                'title': paper.get('title') or row.get('title', ''),
                'authors': '; '.join(name for name, _ in people(paper.get('authors_and_affil', ''))),
                'files': {'paper': paper.get('raw_pdf_path', '')}})
            talk['files'][prefix + 'slides_pdf'] = row.get('slides_pdf', '')
    for session in sessions.values():
        session['papers'].sort(key=lambda paper: paper['position'])
    ordered = sorted(sessions.values(), key=lambda s: (s['start'] or '~', s['key']))
    return ordered, talks


def build(tabs: dict, config: dict) -> dict:
    """What the pages need, from the rows of each tab."""
    zone_name = config.get('timezone', 'UTC')
    zone = venue_zone(zone_name)
    events = tabs.get('EVENTS', [])
    lbd_event = next((e for e in events if e.get('category') == 'LBD'), None)
    sessions, talks = talk_sessions(events, tabs.get('PAPERS', []), tabs.get('ORAL_SESSIONS', []),
                                    tabs.get('AWARD_SESSIONS', []), zone)
    groups = tabs.get('LBD_GROUPS', [])
    return {
        'read_ms': int(time.time() * 1000),
        'timezone': zone_name,
        'lbd_start': iso_time(lbd_event['start_date'], lbd_event['start_time'], zone) if lbd_event else '',
        'lbd_end': iso_time(lbd_event['start_date'], lbd_event['end_time'], zone) if lbd_event else '',
        # The join link of every non-poster live event, LBD included.
        'shared_zoom': lbd_event.get('live_url', '') if lbd_event else '',
        'poster_sessions': poster_sessions(events, config.get('miniconf_url', '').rstrip('/'), zone),
        'lbds': lbd_rows(tabs.get('LBDS', [])),
        'groups': {row['group_id']: row.get('theme', '') for row in groups if row.get('group_id')},
        'group_slack': {row['group_id']: row.get('slack_channel', '') for row in groups if row.get('group_id')},
        'sessions': sessions,
        'talks': talks,
    }


def read(links: dict, config: dict) -> dict:
    """Read every tab there is a link to, at once, and build. RuntimeError when a tab cannot be read."""
    wanted = [name for name in READ if links.get(name)]

    def one(name):
        try:
            return name, sheet_rows(links[name])
        except RuntimeError as error:
            raise RuntimeError(f'SHEET_{name}: {error}') from None

    with ThreadPoolExecutor(len(wanted) or 1) as pool:
        tabs = dict(pool.map(one, wanted))
    return build(tabs, config)


def link_rows(config: dict, env: dict, live: dict) -> list:
    """The Links page: the conference's own links, the Live Database tabs and the Drive folders of .onsite_env,
    then the LINK_* rows written there by hand."""
    site = config.get('miniconf_url', '').rstrip('/')
    rows = [
        ('Conference', 'Miniconf', site, 'The virtual platform'),
        ('Conference', 'Schedule', f'{site}/calendar.html', 'Full calendar'),
        ('Conference', 'Live Overview', f'{site}/live.html', 'What is live now, with headcounts'),
        ('Conference', 'Papers', f'{site}/papers.html', 'All papers and sessions'),
        ('Conference', 'LBDs', f'{site}/lbds.html', 'Late-Breaking/Demo list'),
        ('Conference', 'Warm-up Discussion', f'{site}/lounge.html', 'Paper and LBD discussion boards'),
        ('Conference', 'Official website', config.get('official_site_url', ''), 'ISMIR 2026 main site'),
        ('Zoom', 'Shared webinar', live.get('shared_zoom', ''), 'Join link of every non-poster live event, LBD included'),
        ('Zoom', 'Zoom web portal', 'https://zoom.us/profile', 'Account settings and recordings'),
        ('Slack', 'Workspace', 'https://ismir2026.slack.com', 'Conference Slack'),
        ('Slack', 'Helpdesk', config.get('helpdesk_url', ''), 'Helpdesk channel'),
        ('YouTube', 'Channel', config.get('youtube_channel_url', ''), 'Presentation videos'),
        ('YouTube', 'LBD playlist', config.get('lbd_youtube_playlist_url', ''), 'All LBD videos'),
        ('YouTube', 'YouTube Studio', 'https://studio.youtube.com', 'Log in as zoom.admin.ismir2026@gmail.com'),
        ('Operations', 'GitHub repo', GITHUB, 'This kit and the website code'),
        ('Operations', 'Refresh website', f'{GITHUB}/actions/workflows/refresh-website.yml',
         'Rebuild the miniconf from the Live Database'),
    ]
    rows += [('Live Database', name, env[f'SHEET_{key}'], about) for key, (name, about) in SHEETS.items()
             if env.get(f'SHEET_{key}')]
    rows += [('Materials', f'{key[len("DRIVE_FOLDER_"):]} Drive folder', value, 'See the Materials pages')
             for key, value in env.items() if key.startswith('DRIVE_FOLDER_') and value]
    return [dict(zip(('group', 'name', 'url', 'description'), row)) for row in rows]
