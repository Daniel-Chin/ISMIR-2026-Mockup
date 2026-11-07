"""The LBD and MIREX materials: what Drive has, what this MacBook has, and getting one to the other.

A file counts as current when it has the size Drive reports, so files copied from another MacBook count too.
Everything goes through curl: the Pythons on macOS may have no CA certificates.
"""

from __future__ import annotations

import html
import json
import os
import re
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import unquote

FOLDER_PAGE = 'https://drive.google.com/embeddedfolderview?id={}'
DOWNLOAD = 'https://drive.usercontent.google.com/download?id={}&export=download&confirm=t'
ENTRY = re.compile(r'id="entry-([\w-]+)".*?<a href="([^"]+)".*?flip-entry-title">([^<]+)<', re.S)
KINDS = {'paper': 'papers', 'poster': 'posters', 'video': 'videos', 'thumbnail': 'thumbnails', 'captions': 'captions',
         'channel': 'channels', 'subtitles': 'subtitles'}
# Slack channel QR codes lie loose in their folder: LBD_569_lbd569-groovyui.png, LBD_m7_lbd-m7-a.png (MIREX),
# LBD_group5_lbd-g5-audio.png.
CHANNEL = re.compile(r'LBD_(group)?(m?\d+)_')
# So do the subtitles the players show, from build_subtitles.py: 569.vtt, m1.vtt.
SUBTITLES = re.compile(r'(m?\d+)\.vtt$')
VIDEO_SUFFIXES = {'.mp4', '.mov', '.m4v', '.webm'}
LOOKUPS_AT_ONCE = 8
DOWNLOADS_AT_ONCE = 3
QUOTA_HINT = 'Drive refused it (daily quota?). Try later, or copy media/ from another MacBook.'


def folder_id(link: str) -> str:
    match = re.search(r'/folders/([\w-]+)', link)
    return match[1] if match else link.strip()


def curl(*arguments: str) -> str:
    done = subprocess.run(['curl', '--fail', '--location', '--silent', '--show-error', '--max-time', '60', *arguments],
                          capture_output=True, text=True, encoding='utf-8', errors='replace')
    if done.returncode:
        raise RuntimeError(done.stderr.strip() or f'curl exit code {done.returncode}')
    return done.stdout


def list_folder(identifier: str) -> list:
    return [{'id': entry, 'name': html.unescape(name), 'folder': '/folders/' in href}
            for entry, href, name in ENTRY.findall(curl(FOLDER_PAGE.format(identifier)))]


def drive_size(file_id: str) -> int:
    headers = curl('--range', '0-0', '--dump-header', '-', '--output', os.devnull, DOWNLOAD.format(file_id))
    sizes = re.findall(r'content-range: bytes 0-0/(\d+)', headers, re.I)
    if not sizes:
        raise RuntimeError('Drive did not report a size')
    return int(sizes[-1])


def link_source(link: str):
    """A Drive file or Google Slides link from a sheet -> (id, download URL), or None for anything else.
    Google Slides come as PowerPoint files, whose size Google tells only by sending them."""
    found = re.search(r'(?:[?&]id=|/d/)([\w-]{20,})', link)
    if not found:
        return None
    if 'docs.google.com/presentation' in link:
        return found[1], f'https://docs.google.com/presentation/d/{found[1]}/export/pptx'
    return found[1], DOWNLOAD.format(found[1])


def link_file(url: str) -> dict:
    """The name and size (None when not told) of the file at a download URL."""
    headers = curl('--range', '0-0', '--dump-header', '-', '--output', os.devnull, url)
    names = re.findall(r"filename\*=UTF-8''([^;\r\n]+)", headers, re.I) or re.findall(r'filename="([^"]+)"', headers, re.I)
    sizes = re.findall(r'content-range: bytes 0-0/(\d+)', headers, re.I)
    if not names:
        raise RuntimeError('not shared with anyone with the link?')
    return {'name': unquote(names[-1]), 'size': int(sizes[-1]) if sizes else None}


def downloadable(remote: dict) -> bool:
    """A file of known size, or one whose size only the download tells (an exported Google Slides deck)."""
    return remote.get('size') is not None or bool(remote.get('unsized'))


def kind_of(name: str) -> str:
    """569_lbd.pdf, 569_poster.pdf, 569_thumbnail.png, 569_video.mp4; captions come under many names."""
    if Path(name).suffix.lower() in VIDEO_SUFFIXES:
        return 'video'
    for kind, mark in (('poster', '_poster.'), ('thumbnail', '_thumbnail.'), ('paper', '_lbd.')):
        if mark in name:
            return kind
    return 'captions'


class Materials:
    kinds = KINDS
    listing_name = 'drive_listing.json'

    def __init__(self, media: Path, state: Path, roots: list, lbds: list, screens: dict):
        self.media = media
        self.state = state
        self.roots = roots
        self.use_lbds(lbds)
        self.screen_of = {uid: screen for screen, plan in screens.items() for uid in plan['plays']}
        self.screens = list(screens)
        self.listing_file = state / self.listing_name
        self.listing = (json.loads(self.listing_file.read_text(encoding='utf-8'))
                        if self.listing_file.exists() else {'checked_ms': 0, 'files': {}, 'unmatched': []})
        self.lock = threading.Lock()
        self.job: dict = {}
        self.cancelled = threading.Event()
        self.processes: set = set()

    def use_lbds(self, lbds: list) -> None:
        """The rows to show: uid and title, and the Drive ids of the files the sheet links (file_ids)."""
        self.lbds = lbds
        self.uids = {lbd['uid']: lbd['uid'] for lbd in lbds}  # a Drive folder named after its uid
        self.by_file = {file_id: lbd['uid'] for lbd in lbds for file_id in lbd.get('file_ids', [])}

    def local_file(self, uid: str, kind: str):
        folder = self.media / self.kinds[kind]
        return next((file for file in sorted(folder.glob(f'{uid}.*')) if file.stem == uid), None) if folder.is_dir() else None

    def status(self, uid: str, kind: str) -> dict:
        remote = self.listing['files'].get(uid, {}).get(kind)
        local = self.local_file(uid, kind)
        size = remote.get('size') if remote else None
        local_size = local.stat().st_size if local else None
        if not remote:
            state = 'local' if local else 'none'
        elif not local:
            state = 'missing'
        elif size is None:
            state = 'unknown'
        else:
            state = 'current' if size == local_size else 'changed'
        return {'state': state, 'size': size, 'local_size': local_size, 'remote': bool(remote) and downloadable(remote)}

    def configured(self) -> bool:
        return bool(self.roots)

    def progress(self) -> dict:
        job = dict(self.job)
        if job.get('action') == 'download':
            active = dict(job['active'])  # the download threads change it
            job['done_bytes'] = job['finished_bytes'] + sum(
                part.stat().st_size for part in active.values() if part.exists())
            job['active'] = sorted(active)
        return job

    def snapshot(self) -> dict:
        return {
            'configured': self.configured(),
            'checked_ms': self.listing['checked_ms'],
            'unmatched': self.listing['unmatched'],
            'kinds': list(self.kinds),
            'screens': self.screens,
            'rows': [{'uid': lbd['uid'], 'title': lbd['title'], 'screen': self.screen_of.get(lbd['uid'], ''),
                      'files': {kind: self.status(lbd['uid'], kind) for kind in self.kinds}} for lbd in self.lbds],
            'job': self.progress(),
        }

    def begin(self, job: dict, work, *arguments) -> bool:
        """Run one job at a time, in the background. False when another is running."""
        with self.lock:
            if self.job.get('running'):
                return False
            self.cancelled.clear()
            self.job = {**job, 'running': True, 'failed': [], 'error': ''}

        def run():
            try:
                work(*arguments)
            except Exception as error:  # the page must show it, as nobody watches this thread
                self.job['error'] = str(error)
            self.job['running'] = False

        threading.Thread(target=run, daemon=True).start()
        return True

    def check(self) -> bool:
        return self.begin({'action': 'check', 'done': 0, 'total': 0}, self.check_drive)

    def check_drive(self) -> None:
        entries = []
        for root in self.roots:  # one folder not shared by link must not hide the others
            try:
                entries += list_folder(root)
            except RuntimeError as error:
                self.job['failed'].append(f'Drive folder {root}: {error} (is it shared with anyone with the link?)')
        subfolders = [entry for entry in entries if entry['folder']]
        self.job['total'] = len(subfolders)

        def contents(entry):
            names = list_folder(entry['id'])
            self.job['done'] += 1
            return entry, names

        with ThreadPoolExecutor(LOOKUPS_AT_ONCE) as pool:
            folders = list(pool.map(contents, subfolders))
        # A folder is named after its uid (569), or, for MIREX, after its task: then a file the sheet links is in it.
        owner = {}
        for entry, names in folders:
            uid = self.uids.get(entry['name']) or next((self.by_file[f['id']] for f in names if f['id'] in self.by_file), None)
            if uid:
                owner[entry['id']] = uid
        found = [(owner[entry['id']], file) for entry, names in folders if entry['id'] in owner
                 for file in names if not file['folder']]
        known = set(self.uids.values())
        for entry in entries:
            if entry['folder']:
                continue
            channel, subtitles = CHANNEL.match(entry['name']), SUBTITLES.fullmatch(entry['name'])
            if channel and ('g' if channel[1] else '') + channel[2] in known:
                found.append((('g' if channel[1] else '') + channel[2], {**entry, 'kind': 'channel'}))
            elif subtitles and subtitles[1] in known:
                found.append((subtitles[1], {**entry, 'kind': 'subtitles'}))
        self.job.update(done=0, total=len(found))

        def measure(pair):
            uid, file = pair
            try:
                file['size'] = drive_size(file['id'])
            except RuntimeError as error:
                self.job['failed'].append(f'{file["name"]}: {error}')
            self.job['done'] += 1

        with ThreadPoolExecutor(LOOKUPS_AT_ONCE) as pool:
            list(pool.map(measure, found))
        files: dict = {}
        for uid, file in found:
            files.setdefault(uid, {})[file.get('kind') or kind_of(file['name'])] = {key: file.get(key) for key in ('id', 'name', 'size')}
        self.listing = {'checked_ms': int(time.time() * 1000), 'files': files,
                        'unmatched': sorted(entry['name'] for entry in subfolders if entry['id'] not in owner)}
        self.state.mkdir(exist_ok=True)
        self.listing_file.write_text(json.dumps(self.listing), encoding='utf-8')

    def download(self, keys: list) -> bool:
        items = []
        for key in keys:
            uid, kind = key.split('/')
            remote = self.listing['files'].get(uid, {}).get(kind)
            if remote and kind in self.kinds and downloadable(remote):
                items.append((uid, kind, remote))
        job = {'action': 'download', 'files': len(items), 'files_done': 0, 'active': {}, 'finished_bytes': 0,
               'total_bytes': sum(remote.get('size') or 0 for _, _, remote in items)}
        return self.begin(job, self.download_all, items)

    def download_all(self, items: list) -> None:
        with ThreadPoolExecutor(DOWNLOADS_AT_ONCE) as pool:
            list(pool.map(self.download_one, items))

    def download_one(self, item: tuple) -> None:
        uid, kind, remote = item
        if self.cancelled.is_set():
            return
        label = f'{uid} {kind}'
        # Named after the Drive file, so a partial download is resumed only from the same file; and the
        # kind, as one file can serve twice (a paper's slides for its oral and its award session).
        parts = self.media / '.parts'
        parts.mkdir(parents=True, exist_ok=True)
        part = parts / f'{remote["id"]}-{kind}'
        self.job['active'][label] = part
        try:
            self.transfer(remote, part)
            target_dir = self.media / self.kinds[kind]
            target_dir.mkdir(parents=True, exist_ok=True)
            target = target_dir / f'{uid}{Path(remote["name"]).suffix.lower()}'
            old = self.local_file(uid, kind)
            size = part.stat().st_size
            os.replace(part, target)  # a player reading the old file keeps it until it is done
            if old and old != target:
                old.unlink()
            self.job['finished_bytes'] += size
            self.job['files_done'] += 1
        except RuntimeError as error:
            if not self.cancelled.is_set():
                self.job['failed'].append(f'{label}: {error}')
        finally:
            self.job['active'].pop(label)

    def transfer(self, remote: dict, part: Path) -> None:
        size = remote.get('size')
        if size is None:  # nothing to check a partial file against: start again
            part.unlink(missing_ok=True)
        elif part.exists() and part.stat().st_size >= size:
            if part.stat().st_size == size:
                return
            part.unlink()
        resume = ['--continue-at', '-'] if size is not None else []
        process = subprocess.Popen(
            ['curl', '--fail', '--location', '--silent', '--show-error', '--retry', '3', '--retry-delay', '5',
             *resume, '--output', str(part), remote.get('url') or DOWNLOAD.format(remote['id'])],
            stderr=subprocess.PIPE, text=True, encoding='utf-8', errors='replace')
        self.processes.add(process)
        _, errors = process.communicate()
        self.processes.discard(process)
        if self.cancelled.is_set():
            raise RuntimeError('cancelled')
        if process.returncode == 22:  # an HTTP error, so what came is no use for resuming
            part.unlink(missing_ok=True)
            raise RuntimeError(QUOTA_HINT)
        if process.returncode:
            raise RuntimeError(errors.strip() or f'curl exit code {process.returncode}')
        if size is not None and part.stat().st_size != size:
            part.unlink()
            raise RuntimeError(QUOTA_HINT)

    def cancel(self) -> None:
        self.cancelled.set()
        for process in list(self.processes):
            process.terminate()


# The papers and slides (as PDF) of the oral and award sessions, each linked on its own from the session sheets.
TALK_KINDS = {'paper': 'talks/papers', 'slides_pdf': 'talks/slides_pdf', 'award_slides_pdf': 'talks/award_slides_pdf'}


class LinkMaterials(Materials):
    """Files linked one by one from a sheet rather than laid out in Drive folders."""
    kinds = TALK_KINDS
    listing_name = 'talk_listing.json'

    def __init__(self, media: Path, state: Path, rows: list, links: dict, screens: list):
        super().__init__(media, state, [], rows, {})
        self.has_sheets = False  # whether there are sheets to read the links from, before they have been read
        self.use(rows, links, screens)

    def use(self, rows: list, links: dict, screens: list) -> None:
        """rows: uid, title and screen (its sessions) of each paper; links: uid -> kind -> the sheet's link."""
        self.lbds = rows
        self.uids = {row['uid']: row['uid'] for row in rows}
        self.links = links
        self.screen_of = {row['uid']: row['screen'] for row in rows}
        self.screens = screens

    def configured(self) -> bool:
        return self.has_sheets or bool(self.links)

    def check_drive(self) -> None:
        # Other links (slides on a web page) and notes are for the Talk sessions page to show, not to download.
        wanted = [(uid, kind, source) for uid, kinds in self.links.items() for kind, link in kinds.items()
                  if kind in self.kinds for source in [link_source(link)] if source]
        self.job['total'] = len(wanted)

        def look(item):
            uid, kind, source = item
            try:
                found = link_file(source[1])
                return uid, kind, {'id': source[0], 'url': source[1], 'name': found['name'], 'size': found['size'],
                                   'unsized': found['size'] is None}
            except RuntimeError as error:
                self.job['failed'].append(f'{uid} {kind}: {error}')
                return None
            finally:
                self.job['done'] += 1

        with ThreadPoolExecutor(LOOKUPS_AT_ONCE) as pool:
            found = [result for result in pool.map(look, wanted) if result]
        files: dict = {}
        for uid, kind, remote in found:
            files.setdefault(uid, {})[kind] = remote
        self.listing = {'checked_ms': int(time.time() * 1000), 'files': files, 'unmatched': []}
        self.state.mkdir(exist_ok=True)
        self.listing_file.write_text(json.dumps(self.listing), encoding='utf-8')
