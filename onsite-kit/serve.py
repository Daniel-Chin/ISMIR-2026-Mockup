#!/usr/bin/env python3
"""The local onsite kit: http://127.0.0.1:8765. Python standard library only; see README.md.

Serves web/ and media/, and keeps each LBD screen's schedule in .state/. It answers on this MacBook
only, as .onsite_env holds private links.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

import materials

KIT = Path(__file__).resolve().parent
ENV_FILE = KIT / '.onsite_env'
WEB = KIT / 'web'
MEDIA = KIT / 'media'
STATE = KIT / '.state'
PROBES = STATE / 'probes.json'
LOCAL_HOSTS = {'127.0.0.1', 'localhost'}
mimetypes.add_type('text/javascript', '.mjs')  # pdf.js; older Pythons do not know the extension
POSTER_SCREENS = [f'P{n}' for n in range(1, 5)]  # screens of posters only, alongside the video screens
CLEAR_MS = 30_000  # a poster keeps this far from its own video, as measured lengths differ a little from YouTube's
NO_POSTER_SCREEN = {'m1'}  # the MIREX overview: on the video screen only


def load_env(path=ENV_FILE) -> dict:
    env = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            if line.strip() and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                env[key.strip()] = value.strip()
    return env


def pipe_rows(env: dict, prefix: str, columns: tuple) -> list:
    """The KEY=a | b | c lines, in file order."""
    rows = []
    for key, value in env.items():
        if key.startswith(prefix):
            cells = [cell.strip() for cell in value.split('|', len(columns) - 1)]
            rows.append(dict(zip(columns, cells + [''] * len(columns))))
    return rows


def read_json(path: Path, default):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def write_json(path: Path, data) -> None:
    STATE.mkdir(exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
    os.replace(temporary, path)


def media_files() -> dict:
    """uid -> its video and poster under media/, as URLs, with the video's size."""
    found: dict = {}
    for kind, directory in (('video', 'videos'), ('poster', 'posters'), ('channel', 'channels')):
        folder = MEDIA / directory
        for file in folder.iterdir() if folder.is_dir() else ():
            if not file.name.endswith('.part'):
                found.setdefault(file.stem, {})[kind] = f'/media/{directory}/{file.name}'
                if kind == 'video':
                    found[file.stem]['size'] = file.stat().st_size
    return found


class Kit:
    def __init__(self):
        self.env = load_env()
        self.plan = read_json(KIT / 'lbd_schedule.json', {})
        lbds = json.loads(self.env.get('ONSITE_LBDS', '[]'))
        roots = [materials.folder_id(value) for key, value in self.env.items() if key.startswith('DRIVE_FOLDER_')]
        self.groups = json.loads(self.env.get('ONSITE_LBD_GROUPS', '{}'))
        self.group_slack = json.loads(self.env.get('ONSITE_LBD_GROUP_SLACK', '{}'))
        # Each group's Slack channel QR code is a row of its own in Materials, as g<group>.
        group_rows = [{'uid': f'g{group}', 'title': f'Group {group} Slack channel: {theme}'}
                      for group, theme in self.groups.items()]
        self.materials = materials.Materials(MEDIA, STATE, roots, lbds + group_rows, self.plan.get('screens', {}))
        # Every poster, in group order then uid order, for the poster screens to split between them.
        self.poster_order = [lbd['uid'] for lbd in sorted(lbds, key=lambda lbd: (
            int(lbd.get('group') or 99), lbd['uid'].startswith('m'), int(lbd['uid'].lstrip('m'))))
            if lbd['uid'] not in NO_POSTER_SCREEN]
        self.papers = {lbd['uid']: {k: lbd.get(k, '') for k in ('title', 'authors', 'people', 'mode', 'group', 'slack')}
                       for lbd in lbds}
        start = self.env.get('ONSITE_LBD_START')
        end = self.env.get('ONSITE_LBD_END')
        self.start_ms = int(datetime.fromisoformat(start).timestamp() * 1000) if start else 0
        self.slot_s = int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()) if end else 7200

    def info(self) -> dict:
        return {
            'env_found': ENV_FILE.exists(),
            'timezone': self.env.get('ONSITE_TIMEZONE', 'UTC'),
            'links': pipe_rows(self.env, 'LINK_', ('group', 'name', 'url', 'description')),
            'poster_sessions': json.loads(self.env.get('ONSITE_POSTER_SESSIONS', '[]')),
        }

    def has_screen(self, screen: str) -> bool:
        return screen in self.plan.get('screens', {}) or screen in POSTER_SCREENS

    def default_schedule(self, screen: str) -> dict:
        if screen in POSTER_SCREENS:
            # The plan made by plan_posters.py, the same on every MacBook; worked out here only without one.
            plan = self.plan.get('posters', {}).get(screen) or self.plan_posters(screen)
            return {'rev': 0, 'plays': plan['plays'], 'poster_s': plan['poster_s'], 'timetable_s': 0,
                    'start_ms': self.start_ms}
        plan = self.plan['screens'][screen]
        return {'rev': 0, 'plays': plan['plays'], 'poster_s': plan['poster_s'],
                'timetable_s': plan['timetable_s'], 'start_ms': self.start_ms}

    def plan_posters(self, screen: str) -> dict:
        """A consecutive run of the posters in group order, every poster for the same time, reordered so
        that none is up while its own video or cover is on a video screen."""
        per_screen = -(-len(self.poster_order) // len(POSTER_SCREENS))
        first = POSTER_SCREENS.index(screen) * per_screen
        poster_s = self.slot_s // max(per_screen, 1)
        on_video = self.video_times()

        def free(uid, place):
            begin = self.start_ms + place * poster_s * 1000
            finish = begin + poster_s * 1000
            return not any(begin - CLEAR_MS < end and start < finish + CLEAR_MS for start, end in on_video.get(uid, []))

        return {'plays': arrange(self.poster_order[first:first + per_screen], free), 'poster_s': poster_s}

    def schedule(self, screen: str) -> dict:
        return read_json(STATE / f'screen_{screen}.json', self.default_schedule(screen))

    def video_seconds(self) -> dict:
        """uid -> its video's length: measured on this MacBook where it has been, else the YouTube length."""
        media = media_files()
        seconds = dict(self.plan.get('video_s', {}))
        for uid, probe in read_json(PROBES, {}).items():
            if media.get(uid, {}).get('size') == probe['size'] and probe['seconds']:
                seconds[uid] = probe['seconds']
        return seconds

    def runs(self, screens) -> list:
        """(screen, uid, from ms, to ms) for every play: a video's from its cover to its end, a poster's whole time."""
        seconds = self.video_seconds()
        found = []
        for screen in screens:
            schedule = self.schedule(screen)
            cursor = schedule['start_ms']
            for uid in schedule['plays']:
                length = schedule['timetable_s'] + schedule['poster_s']
                length += 0 if screen in POSTER_SCREENS else seconds.get(uid, 0)
                found.append((screen, uid, cursor, cursor + length * 1000))
                cursor += length * 1000
        return found

    def video_times(self) -> dict:
        times: dict = {}
        for _, uid, start, end in self.runs(self.plan.get('screens', {})):
            times.setdefault(uid, []).append((start, end))
        return times

    def conflicts(self) -> list:
        """Each time a paper's poster is up on a poster screen while its video or cover is on a video screen."""
        on_video = {}
        for screen, uid, start, end in self.runs(self.plan.get('screens', {})):
            on_video.setdefault(uid, []).append((screen, start, end))
        found = []
        for poster_screen, uid, start, end in self.runs(POSTER_SCREENS):
            for video_screen, video_start, video_end in on_video.get(uid, []):
                if start < video_end and video_start < end:
                    found.append({'uid': uid, 'poster_screen': poster_screen, 'video_screen': video_screen,
                                  'from_ms': max(start, video_start), 'to_ms': min(end, video_end)})
        return found

    def lbd(self, screen: str) -> dict:
        if screen in POSTER_SCREENS:
            schedule = self.schedule(screen)
            groups = sorted({self.papers[uid]['group'] for uid in schedule['plays'] if uid in self.papers},
                            key=lambda group: int(group or 99))
            return {**schedule, 'screen': screen, 'kind': 'posters', 'name': f'Poster screen {screen[1:]}',
                    'theme': ' · '.join(self.groups.get(group, group) for group in groups), 'groups': self.groups,
                    'group_slack': self.group_slack,
                    'timezone': self.env.get('ONSITE_TIMEZONE', 'UTC'), 'default_start_ms': self.start_ms,
                    'utc_offset': self.env.get('ONSITE_LBD_START', '+00:00')[-6:], 'slot_s': self.slot_s,
                    'papers': self.papers, 'media': media_files(), 'seconds': dict.fromkeys(self.papers, 0),
                    'problems': {}, 'measured': {}}
        media = media_files()
        probes = read_json(PROBES, {})
        seconds = dict(self.plan['video_s'])
        problems = {}
        for uid, probe in probes.items():
            if media.get(uid, {}).get('size') == probe['size']:
                if probe['seconds']:
                    seconds[uid] = probe['seconds']
                else:
                    problems[uid] = 'unplayable'
        plan = self.plan['screens'][screen]
        return {**self.schedule(screen), 'screen': screen, 'kind': 'videos', 'name': plan['name'],
                'theme': self.groups.get(screen, plan['theme']), 'group_slack': self.group_slack,
                'timezone': self.env.get('ONSITE_TIMEZONE', 'UTC'), 'default_start_ms': self.start_ms,
                'utc_offset': self.env.get('ONSITE_LBD_START', '+00:00')[-6:], 'slot_s': self.slot_s,
                'papers': self.papers, 'media': media, 'seconds': seconds, 'problems': problems,
                'measured': {uid: probe['size'] for uid, probe in probes.items()}}

    def screens(self) -> list:
        media = media_files()
        rows = []
        for screen, plan in self.plan['screens'].items():
            schedule = self.schedule(screen)
            plays = set(schedule['plays'])
            rows.append({'screen': screen, 'name': plan['name'], 'plays': len(schedule['plays']),
                         'poster_s': schedule['poster_s'], 'start_ms': schedule['start_ms'],
                         'missing_videos': sum('video' not in media.get(uid, {}) for uid in plays),
                         'missing_posters': sum('poster' not in media.get(uid, {}) for uid in plays
                                                if schedule['poster_s'])})
        return rows

    def poster_screens(self) -> list:
        media = media_files()
        rows = []
        for screen in POSTER_SCREENS:
            schedule = self.schedule(screen)
            plays = schedule['plays']
            groups = sorted({self.papers[uid]['group'] for uid in plays if uid in self.papers},
                            key=lambda group: int(group or 99))
            rows.append({'screen': screen, 'posters': len(plays), 'poster_s': schedule['poster_s'],
                         'start_ms': schedule['start_ms'], 'timezone': self.env.get('ONSITE_TIMEZONE', 'UTC'),
                         'groups': [self.groups.get(group, group) for group in groups],
                         'first': plays[:1], 'last': plays[-1:],
                         'missing': sum('poster' not in media.get(uid, {}) for uid in plays)})
        return rows

    def save(self, screen: str, body: dict) -> dict:
        """The new schedule, or None when another tab saved first."""
        current = self.schedule(screen)
        if body.get('rev') != current['rev']:
            return None
        if body.get('reset'):
            new = self.default_schedule(screen)
        else:
            new = {key: body[key] for key in ('plays', 'poster_s', 'timetable_s', 'start_ms')}
            if any(uid not in self.papers for uid in new['plays']):
                raise ValueError('unknown paper')
        new['rev'] = current['rev'] + 1
        write_json(STATE / f'screen_{screen}.json', new)
        return new

    def measure(self, measured: dict) -> None:
        write_json(PROBES, {**read_json(PROBES, {}), **measured})


def arrange(uids: list, free) -> list:
    """uids ordered so each sits at a place where free(uid, place), as near its own place as can be.

    A matching of papers to places, by augmenting paths; a paper with no free place left takes an empty one.
    """
    holder: list = [None] * len(uids)

    def place(index, tried):
        for spot in sorted(range(len(uids)), key=lambda spot: abs(spot - index)):
            if spot not in tried and free(uids[index], spot):
                tried.add(spot)
                if holder[spot] is None or place(holder[spot], tried):
                    holder[spot] = index
                    return True
        return False

    stuck = [index for index in range(len(uids)) if not place(index, set())]
    for spot in range(len(uids)):
        if holder[spot] is None:
            holder[spot] = stuck.pop(0)
    return [uids[index] for index in holder]


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    kit: Kit

    def log_message(self, *args):
        pass

    def local_only(self) -> bool:
        # A website can point its own domain at 127.0.0.1, so the bind address alone is not enough.
        host = self.headers.get('Host', '').rsplit(':', 1)[0]
        if host in LOCAL_HOSTS:
            return True
        self.send_error(403)
        return False

    def send_json(self, data, status=200):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(body)

    def send_file(self, root: Path, relative: str):
        file = (root / relative).resolve()
        if root.resolve() not in file.parents or not file.is_file():
            self.send_error(404)
            return
        size = file.stat().st_size
        start, end = 0, size - 1
        # Seeking a <video> needs byte ranges, which SimpleHTTPRequestHandler does not serve.
        wanted = re.fullmatch(r'bytes=(\d*)-(\d*)', self.headers.get('Range', ''))
        if wanted and wanted[1]:
            start = int(wanted[1])
            end = min(int(wanted[2] or end), end)
        elif wanted and wanted[2]:
            start = max(size - int(wanted[2]), 0)
        if start >= size and size:
            self.send_error(416)
            return
        self.send_response(206 if wanted else 200)
        self.send_header('Content-Type', mimetypes.guess_type(file.name)[0] or 'application/octet-stream')
        self.send_header('Content-Length', str(end - start + 1))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Cache-Control', 'no-cache')
        if wanted:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        with open(file, 'rb') as stream:
            stream.seek(start)
            left = end - start + 1
            try:
                while left > 0:
                    chunk = stream.read(min(1 << 20, left))
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    left -= len(chunk)
            except (BrokenPipeError, ConnectionResetError):
                self.close_connection = True  # the browser moved on to another range

    def materials_action(self, body: dict):
        store = self.kit.materials
        if body.get('action') == 'cancel':
            store.cancel()
            self.send_json({})
        elif store.check() if body.get('action') == 'check' else store.download(body.get('files', [])):
            self.send_json({})
        else:
            self.send_json({'error': 'Wait for the running job to finish.'}, 409)

    def do_GET(self):
        if not self.local_only():
            return
        path = unquote(urlsplit(self.path).path)
        screen = re.fullmatch(r'/api/lbd/(\w+)', path)
        if path == '/api/info':
            self.send_json(self.kit.info())
        elif path == '/api/lbd':
            self.send_json(self.kit.screens())
        elif path == '/api/materials':
            self.send_json(self.kit.materials.snapshot())
        elif path == '/api/posters':
            self.send_json(self.kit.poster_screens())
        elif path == '/api/conflicts':
            self.send_json({'timezone': self.kit.env.get('ONSITE_TIMEZONE', 'UTC'), 'conflicts': self.kit.conflicts()})
        elif screen and self.kit.has_screen(screen[1]):
            self.send_json(self.kit.lbd(screen[1]))
        elif path.startswith('/media/'):
            self.send_file(MEDIA, path[len('/media/'):])
        elif path == '/logo.png':  # the conference logo, as on the program site
            self.send_file(KIT.parent / 'static' / 'images', 'ismir_tabicon.png')
        else:
            self.send_file(WEB, 'index.html' if path == '/' else path.lstrip('/'))

    def do_POST(self):
        if not self.local_only():
            return
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))) or b'{}')
        path = urlsplit(self.path).path
        screen = re.fullmatch(r'/api/lbd/(\w+)', path)
        if path == '/api/measured':
            self.kit.measure(body)
            self.send_json({})
        elif path == '/api/materials':
            self.materials_action(body)
        elif screen and self.kit.has_screen(screen[1]):
            try:
                saved = self.kit.save(screen[1], body)
            except (KeyError, TypeError, ValueError) as error:
                self.send_json({'error': str(error)}, 400)
                return
            if saved is None:
                self.send_json({'error': 'This screen was changed elsewhere; reload.'}, 409)
            else:
                self.send_json(saved)
        else:
            self.send_error(404)


class Server(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        if not isinstance(sys.exc_info()[1], ConnectionError):  # a closed browser tab is no error
            super().handle_error(request, client_address)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if not ENV_FILE.exists():
        print(f'WARNING: {ENV_FILE} is missing: no links, sessions or LBDs will show.', file=sys.stderr)
    Handler.kit = Kit()
    server = Server(('127.0.0.1', args.port), Handler)
    print(f'Onsite kit: http://127.0.0.1:{args.port}  (Ctrl-C to stop)')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
