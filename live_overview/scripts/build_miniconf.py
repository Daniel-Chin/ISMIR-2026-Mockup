#!/usr/bin/env python3
"""Build the standalone Live Overview (own nav, linked from the miniconf menu) into live_overview/build.

Owned outputs (see integration.md):
  build/live.html   the page; miniconf's nav links here directly (no iframe wrapper)
  build/live_overview/     assets, config and the frozen schedule snapshot
Nothing else under build/ is written or removed.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_public_site import ASSETS, PUBLIC_RELEASE, snapshot  # noqa: E402
import update_schedule  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
DEFAULT_API_ORIGIN = 'https://ismir-backend-test.linliwei3916.workers.dev'
PAGE = 'live.html'
ASSET_DIR = 'live_overview'


def read_config(path):
    values = yaml.safe_load(path.read_text(encoding='utf-8'))
    conf = {key: str(values.get(key) or '') for key in ('name', 'date', 'timezone', 'miniconf_url')}
    missing = [key for key, value in conf.items() if not value]
    if missing:
        raise ValueError(f'{path}: missing {", ".join(missing)}')
    conf['miniconf_url'] = conf['miniconf_url'].rstrip('/')
    conf['official_site_url'] = str(values.get('official_site_url') or '')  # optional
    return conf


def render_page(text, asset_prefix, home):
    text = re.sub(r'(\.js|\.css)\?v=[^"\s]+', lambda m: m.group(1) + '?v=' + PUBLIC_RELEASE, text)
    text = re.sub(r'(data-build-version>)[^<]*', lambda m: m.group(1) + 'UI ' + PUBLIC_RELEASE, text)
    # Root-absolute links were written for a dedicated host; here pages live at
    # {prefix}/live.html and {prefix}/live_overview/*.
    def relink(m):
        path = m[2]
        target = home + path if not path or path.startswith('#') else asset_prefix + path
        return f'{m[1]}="{target}"'
    text = re.sub(r'(src|href)="/(?!/)([^"]*)"', relink, text)
    return text


def warn(message):
    # GitHub Actions renders this as an annotation; locally it is a plain line.
    print(f'::warning title=Live Overview::{message}', flush=True)


def load_schedule(data_path, conf):
    """CSV -> schedule. Sheet problems become warnings; returns (schedule, notes, problems)."""
    problems = []
    try:
        schedule, notes = update_schedule.convert(data_path, conf, warnings=problems)
    except (ValueError, KeyError, OSError) as error:
        # Unreadable sheets: still ship the page (live data comes from the backend), without a snapshot.
        problems.append(f'schedule not built: {error}')
        schedule, notes = {'conference': {}, 'events': []}, []
    return schedule, notes, problems


def admin_request(api_origin, key, method, path, body=None):
    request = urllib.request.Request(
        api_origin + path, method=method,
        data=None if body is None else json.dumps(body, ensure_ascii=False).encode('utf-8'),
        headers={'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json', 'User-Agent': 'ismir-live-overview-build'})
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode('utf-8'))


def sync_backend(schedule, api_origin, key):
    """Upload the CSV schedule through the backend's existing /api/admin/import.

    The digest lets unchanged sheets skip the import, which would otherwise bump the
    schedule revision and make every open page refetch. The debug clock is left untouched.
    """
    content = {k: v for k, v in schedule.items() if k not in ('generatedAt', 'sourceDigest')}
    digest = hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode('utf-8')).hexdigest()
    current = admin_request(api_origin, key, 'GET', '/api/admin/export')
    if current.get('schedule', {}).get('sourceDigest') == digest:
        print('Live Overview: backend schedule already up to date')
        return
    result = admin_request(api_origin, key, 'POST', '/api/admin/import', {'schedule': {**schedule, 'sourceDigest': digest}})
    if not result.get('ok'):
        raise ValueError(result.get('error') or 'import rejected')
    print(f"Live Overview: backend schedule updated ({result.get('events')} events)")


def write_site(out, api_origin, conf, schedule):
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='live-overview-', dir=out.parent) as tmp:
        stage = Path(tmp)
        assets = stage / ASSET_DIR
        assets.mkdir()
        for name in ASSETS:
            text = (ROOT / 'overview-source' / name).read_text(encoding='utf-8')
            if name.endswith('.js'):
                text = re.sub(r"const ISMIR_BUILD_VERSION = '[^']+';", f"const ISMIR_BUILD_VERSION = '{PUBLIC_RELEASE}';", text)
            if name == 'index.html':
                (stage / PAGE).write_text(render_page(text, ASSET_DIR + '/', ''), encoding='utf-8')
                continue
            if name.endswith('.html'):
                text = render_page(text, './', '../' + PAGE)
            (assets / name).write_text(text, encoding='utf-8')
        config = {
            'staticHosting': True,
            'apiOrigin': api_origin,
            'conference': {'name': conf['name'], 'date': conf['date'], 'timezone': conf['timezone'], 'miniconfUrl': conf['miniconf_url'], 'officialSiteUrl': conf['official_site_url']},
        }
        (assets / 'public-site-config.js').write_text(
            'window.ISMIR_PUBLIC_CONFIG = Object.assign(' + json.dumps(config, ensure_ascii=False)
            + ", { fallbackUrl: new URL('schedule-snapshot.json', document.currentScript.src).href });\n", encoding='utf-8')
        # snapshot() drops every link, so raw Zoom live_url never reaches the static site.
        (assets / 'schedule-snapshot.json').write_text(json.dumps(snapshot(schedule), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

        (out / PAGE).unlink(missing_ok=True)
        shutil.rmtree(out / ASSET_DIR, ignore_errors=True)
        shutil.move(str(stage / PAGE), out / PAGE)
        shutil.move(str(assets), out / ASSET_DIR)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--mockup', action='store_true', help='Read ../sitedata_mock instead of ../sitedata (never syncs the backend)')
    parser.add_argument('--data', help='Explicit data_path (overrides --mockup; never syncs the backend)')
    parser.add_argument('--out', default=str(ROOT / 'build'))
    parser.add_argument('--api-origin', default=os.environ.get('LIVE_OVERVIEW_API_ORIGIN', DEFAULT_API_ORIGIN))
    args = parser.parse_args()
    parts = urlsplit(args.api_origin)
    if parts.scheme != 'https' or not parts.netloc or parts.path or parts.query or parts.fragment:
        parser.error('API origin must be an HTTPS origin without a path')
    data_path = (Path(args.data) if args.data else REPO / ('sitedata_mock' if args.mockup else 'sitedata')).resolve()

    conf = read_config(data_path / 'config.yml')
    schedule, notes, problems = load_schedule(data_path, conf)
    for note in notes:
        print(note)
    for message in problems:
        warn(message)
    write_site(Path(args.out).resolve(), args.api_origin, conf, schedule)
    print(f"Live Overview: {len(schedule['events'])} events from {data_path} -> {args.out}")

    # Only the production sheets may replace the live backend schedule.
    key = os.environ.get('LIVE_OVERVIEW_ADMIN_KEY', '').strip()
    if args.mockup or args.data or not key:
        print('Live Overview: backend sync skipped (' + ('not production data' if key else 'no LIVE_OVERVIEW_ADMIN_KEY') + ')')
    elif problems:
        warn('backend sync skipped: fix the sheet problems above; the backend keeps its last good schedule')
    else:
        try:
            sync_backend(schedule, args.api_origin, key)
        except (urllib.error.URLError, ValueError, OSError) as error:
            warn(f'backend sync failed, the backend keeps its last schedule: {error}')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, OSError) as error:
        print('Live Overview build failed: ' + str(error), file=sys.stderr)
        sys.exit(1)
