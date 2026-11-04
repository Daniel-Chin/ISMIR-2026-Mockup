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

FOLDER_PAGE = 'https://drive.google.com/embeddedfolderview?id={}'
DOWNLOAD = 'https://drive.usercontent.google.com/download?id={}&export=download&confirm=t'
ENTRY = re.compile(r'id="entry-([\w-]+)".*?<a href="([^"]+)".*?flip-entry-title">([^<]+)<', re.S)
KINDS = {'paper': 'papers', 'poster': 'posters', 'video': 'videos', 'thumbnail': 'thumbnails', 'captions': 'captions'}
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


def kind_of(name: str) -> str:
    """569_lbd.pdf, 569_poster.pdf, 569_thumbnail.png, 569_video.mp4; captions come under many names."""
    if Path(name).suffix.lower() in VIDEO_SUFFIXES:
        return 'video'
    for kind, mark in (('poster', '_poster.'), ('thumbnail', '_thumbnail.'), ('paper', '_lbd.')):
        if mark in name:
            return kind
    return 'captions'


class Materials:
    def __init__(self, media: Path, state: Path, roots: list, lbds: list, screens: dict):
        self.media = media
        self.state = state
        self.roots = roots
        self.lbds = lbds
        self.uids = {lbd.get('folder', lbd['uid']): lbd['uid'] for lbd in lbds}
        self.screen_of = {uid: screen for screen, plan in screens.items() for uid in plan['plays']}
        self.listing_file = state / 'drive_listing.json'
        self.listing = (json.loads(self.listing_file.read_text(encoding='utf-8'))
                        if self.listing_file.exists() else {'checked_ms': 0, 'files': {}, 'unmatched': []})
        self.lock = threading.Lock()
        self.job: dict = {}
        self.cancelled = threading.Event()
        self.processes: set = set()

    def local_file(self, uid: str, kind: str):
        folder = self.media / KINDS[kind]
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
        return {'state': state, 'size': size, 'local_size': local_size}

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
            'configured': bool(self.roots),
            'checked_ms': self.listing['checked_ms'],
            'unmatched': self.listing['unmatched'],
            'kinds': list(KINDS),
            'rows': [{'uid': lbd['uid'], 'title': lbd['title'], 'screen': self.screen_of.get(lbd['uid'], ''),
                      'files': {kind: self.status(lbd['uid'], kind) for kind in KINDS}} for lbd in self.lbds],
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
        subfolders = [entry for root in self.roots for entry in list_folder(root) if entry['folder']]
        matched = [entry for entry in subfolders if entry['name'] in self.uids]
        self.job['total'] = len(matched)

        def contents(entry):
            names = list_folder(entry['id'])
            self.job['done'] += 1
            return entry, names

        with ThreadPoolExecutor(LOOKUPS_AT_ONCE) as pool:
            folders = list(pool.map(contents, matched))
        found = [(self.uids[entry['name']], file) for entry, names in folders for file in names if not file['folder']]
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
            files.setdefault(uid, {})[kind_of(file['name'])] = {key: file.get(key) for key in ('id', 'name', 'size')}
        self.listing = {'checked_ms': int(time.time() * 1000), 'files': files,
                        'unmatched': sorted(entry['name'] for entry in subfolders if entry['name'] not in self.uids)}
        self.state.mkdir(exist_ok=True)
        self.listing_file.write_text(json.dumps(self.listing), encoding='utf-8')

    def download(self, keys: list) -> bool:
        items = []
        for key in keys:
            uid, kind = key.split('/')
            remote = self.listing['files'].get(uid, {}).get(kind)
            if remote and remote.get('size') is not None:
                items.append((uid, kind, remote))
        job = {'action': 'download', 'files': len(items), 'files_done': 0, 'active': {}, 'finished_bytes': 0,
               'total_bytes': sum(remote['size'] for _, _, remote in items)}
        return self.begin(job, self.download_all, items)

    def download_all(self, items: list) -> None:
        with ThreadPoolExecutor(DOWNLOADS_AT_ONCE) as pool:
            list(pool.map(self.download_one, items))

    def download_one(self, item: tuple) -> None:
        uid, kind, remote = item
        if self.cancelled.is_set():
            return
        label = f'{uid} {kind}'
        # Named after the Drive file, so a partial download is resumed only from the same file.
        parts = self.media / '.parts'
        parts.mkdir(parents=True, exist_ok=True)
        part = parts / remote['id']
        self.job['active'][label] = part
        try:
            self.transfer(remote, part)
            target_dir = self.media / KINDS[kind]
            target_dir.mkdir(exist_ok=True)
            target = target_dir / f'{uid}{Path(remote["name"]).suffix.lower()}'
            old = self.local_file(uid, kind)
            os.replace(part, target)  # a player reading the old file keeps it until it is done
            if old and old != target:
                old.unlink()
            self.job['finished_bytes'] += remote['size']
            self.job['files_done'] += 1
        except RuntimeError as error:
            if not self.cancelled.is_set():
                self.job['failed'].append(f'{label}: {error}')
        finally:
            self.job['active'].pop(label)

    def transfer(self, remote: dict, part: Path) -> None:
        if part.exists() and part.stat().st_size >= remote['size']:
            if part.stat().st_size == remote['size']:
                return
            part.unlink()
        process = subprocess.Popen(
            ['curl', '--fail', '--location', '--silent', '--show-error', '--retry', '3', '--retry-delay', '5',
             '--continue-at', '-', '--output', str(part), DOWNLOAD.format(remote['id'])],
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
        if part.stat().st_size != remote['size']:
            part.unlink()
            raise RuntimeError(QUOTA_HINT)

    def cancel(self) -> None:
        self.cancelled.set()
        for process in list(self.processes):
            process.terminate()
