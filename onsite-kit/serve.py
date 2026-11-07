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
import subprocess
import sys
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

import lbdplan
import livedb
import materials

KIT = Path(__file__).resolve().parent
ENV_FILE = KIT / '.onsite_env'
WEB = KIT / 'web'
MEDIA = KIT / 'media'
STATE = KIT / '.state'
PROBES = STATE / 'probes.json'
LOCAL_HOSTS = {'127.0.0.1', 'localhost'}
mimetypes.add_type('text/javascript', '.mjs')  # pdf.js; older Pythons do not know the extension
mimetypes.add_type('text/vtt', '.vtt')  # subtitles; Chrome shows no track served as anything else
POSTER_SCREENS = lbdplan.POSTER_SCREENS
arrange = lbdplan.arrange


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
    for kind, directory in (('video', 'videos'), ('poster', 'posters'), ('channel', 'channels'), ('subtitles', 'subtitles')):
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
        # The plan this MacBook last worked out from the Live Database, else the one in the repo (the reference).
        self.reference = read_json(KIT / 'lbd_schedule.json', {})
        self.plan = read_json(STATE / 'lbd_plan.json', self.reference)
        self.config = livedb.site_config(KIT.parent / 'sitedata' / 'config.yml')
        self.sheet_links = {name: self.env.get(f'SHEET_{name}', '') for name in livedb.SHEETS}
        roots = [materials.folder_id(value) for key, value in self.env.items() if key.startswith('DRIVE_FOLDER_') and value.strip()]
        self.materials = materials.Materials(MEDIA, STATE, roots, [], self.plan.get('screens', {}))
        self.talk_materials = materials.LinkMaterials(MEDIA, STATE, [], {}, [])
        self.talk_materials.has_sheets = bool(self.sheet_links['ORAL_SESSIONS'] or self.sheet_links['AWARD_SESSIONS'])
        self.live_lock = threading.Lock()
        self.live_error = ''
        # The last reading of the Live Database, until the next one: the pages work without a network.
        self.use_live({**livedb.EMPTY, **read_json(STATE / 'live.json', {})})

    def use_live(self, live: dict) -> None:
        """Take a reading of the Live Database: the LBDs, groups and LBD slot, and the oral and award sessions."""
        self.live = live
        self.timezone = live['timezone']
        lbds = live['lbds']
        self.groups, self.group_slack = live['groups'], live['group_slack']
        # Each group's Slack channel QR code is a row of its own in Materials, as g<group>.
        group_rows = [{'uid': f'g{group}', 'title': f'Group {group} Slack channel: {theme}'}
                      for group, theme in self.groups.items()]
        self.materials.use_lbds(lbds + group_rows)
        # Every poster to show, in group order then uid order, for the poster screens to split between them.
        self.poster_order = [lbd['uid'] for lbd in sorted(lbds, key=lambda lbd: (int(lbd.get('group') or 99),
                                                                                lbdplan.order(lbd['uid'])))
                             if lbdplan.on_poster(lbd)]
        self.papers = {lbd['uid']: {k: lbd.get(k, '') for k in ('title', 'authors', 'people', 'mode', 'ok', 'group', 'slack')}
                       for lbd in lbds}
        start, end = live['lbd_start'], live['lbd_end']
        self.start_ms = int(datetime.fromisoformat(start).timestamp() * 1000) if start else 0
        self.slot_s = int((datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()) if end else 7200
        self.utc_offset = start[-6:] if start else '+00:00'
        self.talk_sessions, self.talks = live['sessions'], live['talks']
        sessions_of: dict = {}
        for session in self.talk_sessions:
            for paper in session['papers']:
                sessions_of.setdefault(paper['uid'], []).append(session['key'])
        rows = [{'uid': uid, 'title': talk['title'], 'screen': ' '.join(sessions_of.get(uid, []))}
                for uid, talk in sorted(self.talks.items(), key=lambda item: int(item[0]) if item[0].isdigit() else 0)]
        self.talk_materials.use(rows, {uid: talk['files'] for uid, talk in self.talks.items()},
                                [session['key'] for session in self.talk_sessions])

    def read_live(self) -> None:
        """Read the Live Database now, and keep the reading. RuntimeError when it cannot be read."""
        if not any(self.sheet_links.values()):
            raise RuntimeError('No SHEET_* links in .onsite_env: run make_env.py')
        with self.live_lock:
            try:
                live = livedb.read(self.sheet_links, self.config)
            except RuntimeError as error:
                self.live_error = str(error)
                raise
            self.live_error = ''
            write_json(STATE / 'live.json', live)
            self.use_live(live)

    def live_status(self) -> dict:
        return {'read_ms': self.live['read_ms'], 'error': self.live_error, 'timezone': self.timezone,
                'configured': any(self.sheet_links.values())}

    def info(self) -> dict:
        return {
            'env_found': ENV_FILE.exists(),
            'timezone': self.timezone,
            'links': livedb.link_rows(self.config, self.env, self.live)
            + pipe_rows(self.env, 'LINK_', ('group', 'name', 'url', 'description')),
            'poster_sessions': self.live['poster_sessions'],
        }

    def has_screen(self, screen: str) -> bool:
        return screen in self.plan.get('screens', {}) or screen in POSTER_SCREENS

    def default_schedule(self, screen: str) -> dict:
        if screen in POSTER_SCREENS:
            # The plan's, the same on every MacBook; worked out here only without one.
            plan = self.plan.get('posters', {}).get(screen) or self.plan_posters(screen)
            return {'rev': 0, 'plays': plan['plays'], 'poster_s': plan['poster_s'], 'timetable_s': 0,
                    'start_ms': self.start_ms}
        plan = self.plan['screens'][screen]
        return {'rev': 0, 'plays': plan['plays'], 'poster_s': plan['poster_s'],
                'timetable_s': plan['timetable_s'], 'start_ms': self.start_ms}

    def plan_posters(self, screen: str) -> dict:
        """This poster screen's run, against the video screens as they are now."""
        return lbdplan.plan_posters(self.poster_order, self.video_times(), self.start_ms, self.slot_s)[screen]

    def video_length(self, uid: str):
        """A video's length for planning: as its file here states it, else the YouTube length. The same on every
        MacBook with the same files, unlike the lengths Chrome measures."""
        file = media_files().get(uid, {}).get('video')
        found = lbdplan.mp4_seconds(MEDIA / file[len('/media/'):]) if file else None
        return found or self.reference.get('video_s', {}).get(uid)

    def new_plan(self) -> tuple:
        """The plan the Live Database asks for now, and what could not be planned."""
        return lbdplan.build(self.reference, self.live['lbds'], self.groups, self.video_length, self.start_ms, self.slot_s)

    def plan_status(self) -> dict:
        plan, problems = self.new_plan()
        return {'changes': lbdplan.changes(self.plan, plan), 'problems': problems,
                'planned_ms': self.plan.get('planned_ms', 0), 'read_ms': self.live['read_ms'], 'timezone': self.timezone}

    def apply_plan(self) -> dict:
        """Take the plan the Live Database asks for. A screen whose plays change loses its edits in Manage (its
        start time stays), so it shows the new plan."""
        plan, problems = self.new_plan()
        changed = [line.split(':')[0] for line in lbdplan.changes(self.plan, plan)]
        old = {screen: self.schedule(screen) for screen in [*self.plan.get('screens', {}), *POSTER_SCREENS]}
        plan['planned_ms'] = int(datetime.now().timestamp() * 1000)
        write_json(STATE / 'lbd_plan.json', plan)
        self.plan = plan
        self.materials.screen_of = {uid: screen for screen, body in plan['screens'].items() for uid in body['plays']}
        reset = []
        for screen, schedule in old.items():
            saved = STATE / f'screen_{screen}.json'
            label = f'Poster screen {screen}' if screen in POSTER_SCREENS else f'Screen {screen}'
            if saved.exists() and label in changed:
                write_json(saved, {**self.default_schedule(screen), 'start_ms': schedule['start_ms'], 'rev': schedule['rev'] + 1})
                reset.append(screen)
        return {**self.plan_status(), 'reset': reset, 'problems': problems}

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
                    'timezone': self.timezone, 'default_start_ms': self.start_ms,
                    'utc_offset': self.utc_offset, 'slot_s': self.slot_s,
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
                'timezone': self.timezone, 'default_start_ms': self.start_ms,
                'utc_offset': self.utc_offset, 'slot_s': self.slot_s,
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
                         'start_ms': schedule['start_ms'], 'timezone': self.timezone,
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

    def sessions(self) -> dict:
        """The oral and award sessions, each paper with which of its files this MacBook has."""
        store = self.talk_materials
        found = []
        for session in self.talk_sessions:
            prefix = 'award_' if session['kind'] == 'award' else ''
            papers = []
            for paper in session['papers']:
                talk = self.talks.get(paper['uid'], {})
                here = {role: (kind, store.local_file(paper['uid'], kind))
                        for role, kind in (('slides', prefix + 'slides_pdf'), ('paper', 'paper'))}
                files = {role: {'kind': kind, 'name': file.name} for role, (kind, file) in here.items() if file}
                link = talk.get('files', {}).get(prefix + 'slides_pdf', '')
                # What the sheet has instead of a file: slides on a web page, or a note in place of a link.
                web = link if link.startswith('http') and not materials.link_source(link) else ''
                note = link if link and not link.startswith('http') else ''
                papers.append({**paper, 'title': talk.get('title', ''), 'authors': talk.get('authors', ''), 'files': files,
                               'slides_linked': bool(link), 'slides_web': web, 'slides_note': note})
            found.append({**session, 'papers': papers})
        return {'timezone': self.timezone, 'sessions': found, 'read_ms': self.live['read_ms'],
                'configured': self.talk_materials.has_sheets}

    def open_talk_file(self, uid: str, kind: str, reveal: bool) -> bool:
        """Open a downloaded paper or slides file in its own app, or show it in Finder. False when it is not here."""
        if kind not in self.talk_materials.kinds or uid not in self.talks:
            return False
        file = self.talk_materials.local_file(uid, kind)
        if not file:
            return False
        if sys.platform == 'darwin':
            subprocess.Popen(['open', '-R', str(file)] if reveal else ['open', str(file)])
        elif sys.platform == 'win32':
            if reveal:
                subprocess.Popen(['explorer', f'/select,{file}'])
            else:
                os.startfile(file)  # noqa: S606 (a file of ours, opened by its own app)
        else:
            subprocess.Popen(['xdg-open', str(file.parent if reveal else file)])
        return True


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

    def same_site(self) -> bool:
        """A request this kit's own pages made: any other site's request comes with its Origin, or as a
        form, which cannot send JSON. For actions that reach beyond the browser, such as opening a file."""
        origin = self.headers.get('Origin')
        if (origin and urlsplit(origin).netloc != self.headers.get('Host')
                or not self.headers.get('Content-Type', '').startswith('application/json')):
            self.send_error(403)
            return False
        return True

    def read_live(self) -> bool:
        try:
            self.kit.read_live()
            return True
        except RuntimeError as error:
            self.send_json({'error': f'Could not read the Live Database: {error}'}, 502)
            return False

    def materials_action(self, store, body: dict):
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
        elif path == '/api/talk-materials':
            self.send_json(self.kit.talk_materials.snapshot())
        elif path == '/api/talks':
            self.send_json(self.kit.sessions())
        elif path == '/api/live':
            self.send_json(self.kit.live_status())
        elif path == '/api/lbd-plan':
            self.send_json(self.kit.plan_status())
        elif path == '/api/posters':
            self.send_json(self.kit.poster_screens())
        elif path == '/api/conflicts':
            self.send_json({'timezone': self.kit.timezone, 'conflicts': self.kit.conflicts()})
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
        elif path == '/api/live':  # read the Live Database again
            if self.read_live():
                self.send_json(self.kit.live_status())
        elif path == '/api/lbd-plan':  # take the plan the Live Database asks for, as read just now
            if self.read_live():
                self.send_json(self.kit.apply_plan())
        elif path in ('/api/materials', '/api/talk-materials'):
            # The Live Database first: it may list new LBDs or new slides.
            if body.get('action') != 'check' or self.read_live():
                self.materials_action(self.kit.materials if path == '/api/materials' else self.kit.talk_materials, body)
        elif path == '/api/talks/open':
            if self.same_site():
                opened = self.kit.open_talk_file(str(body.get('uid', '')), str(body.get('kind', '')), bool(body.get('reveal')))
                self.send_json({} if opened else {'error': 'Not downloaded on this MacBook: see Paper materials.'},
                               200 if opened else 404)
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


def _quietly(work) -> None:
    try:
        work()
    except RuntimeError as error:
        print(f'Live Database not read: {error}; showing the last reading', file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if not ENV_FILE.exists():
        print(f'WARNING: {ENV_FILE} is missing: no links, sessions or LBDs will show.', file=sys.stderr)
    Handler.kit = Kit()
    threading.Thread(target=lambda: _quietly(Handler.kit.read_live), daemon=True).start()
    server = Server(('127.0.0.1', args.port), Handler)
    print(f'Onsite kit: http://127.0.0.1:{args.port}  (Ctrl-C to stop)')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
