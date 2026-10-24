#!/usr/bin/env python3
"""Build the standalone Live Overview (own nav, linked from the miniconf menu) into live_overview/build.

Owned outputs (see integration.md):
  build/live.html   the page; miniconf's nav links here directly (no iframe wrapper)
  build/live-debug.html   the same page for testing (debug_page): features under test and the
                    organisers' test clock apply there only. Not linked from anywhere.
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
from site_files import ASSETS, asset_source, content_version, snapshot  # noqa: E402
import update_schedule  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
PAGE = 'live.html'
DEBUG_PAGE = 'live-debug.html'
ASSET_DIR = 'live_overview'


def read_config(path):
    values = yaml.safe_load(path.read_text(encoding='utf-8'))
    conf = {key: str(values.get(key) or '') for key in ('name', 'date', 'timezone', 'miniconf_url')}
    missing = [key for key, value in conf.items() if not value]
    if missing:
        raise ValueError(f'{path}: missing {", ".join(missing)}')
    conf['miniconf_url'] = conf['miniconf_url'].rstrip('/')
    conf['official_site_url'] = str(values.get('official_site_url') or '')  # optional
    # The two backends (Cloudflare Workers). live_overview_api: schedule and live counts; use its
    # custom domain, *.workers.dev is blocked on some networks (e.g. mainland China). warmup_api:
    # the Warm-up Discussion's, for the easter egg's sign-in and finders (egg-account.js).
    conf['live_overview_api'] = str(values.get('live_overview_api') or '').rstrip('/')
    conf['warmup_api'] = str(values.get('warmup_api') or '').rstrip('/')
    conf['slack_app_name'] = str(values.get('slack_app_name') or '')
    return conf


def render_page(text, asset_prefix, home, version):
    text = re.sub(r'(data-build-version>)[^<]*', lambda m: m.group(1) + 'UI ' + version, text)
    # Root-absolute links were written for a dedicated host; here pages live at
    # {prefix}/live.html and {prefix}/live_overview/*. ?v=: browsers cache GitHub Pages files for
    # 10 minutes, so a fresh page must not run against stale scripts.
    def relink(m):
        path, frag = m[2], m[3] or ''
        if not path:   # "/" or "/#section": the live page
            return f'{m[1]}="{home + frag}"'
        return f'{m[1]}="{asset_prefix + path}?v={version}{frag}"'
    text = re.sub(r'(src|href)="/(?!/)([^"?#]*)(#[^"]*)?"', relink, text)
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
        return {'conference': {}, 'events': []}, [], problems
    # Events only on the Live Overview (extra-events.json), never on the miniconf.
    taken = {e['id'] for e in schedule['events']}
    for event in update_schedule.extra_events(conf, problems.append):
        if event['id'] in taken:
            problems.append(f"extra-events.json: {event['id']} is also in events.csv")
            continue
        schedule['events'].append(event)
    schedule['events'].sort(key=lambda e: (e['startsAt'], e['id']))
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


def debug_page(page):
    """live.html -> live-debug.html: the same page, marked as the debug channel (features.js).

    These three edits are the only differences; test/test_debug_page.py checks it, so a feature
    tested here behaves the same on live.html once features.js ships it.
    """
    marked = page.replace('<html lang="en"', '<html lang="en" data-channel="debug"', 1)
    marked = re.sub(r'<title>', '<title>[DEBUG] ', marked, count=1)
    marked = marked.replace('<meta charset="utf-8" />', '<meta charset="utf-8" />\n  <meta name="robots" content="noindex" />', 1)
    if marked.count('data-channel="debug"') != 1 or '[DEBUG] ' not in marked or 'name="robots"' not in marked:
        raise ValueError('live-debug.html: index.html no longer has the expected <html lang="en">, <title> or charset tag')
    return marked


def write_site(out, api_origin, conf, schedule):
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='live-overview-', dir=out.parent) as tmp:
        stage = Path(tmp)
        assets = stage / ASSET_DIR
        assets.mkdir()
        texts = {name: asset_source(name).read_text(encoding='utf-8') for name in ASSETS}
        config = {
            'apiOrigin': api_origin,
            'loungeOrigin': os.environ.get('WARMUP_API_ORIGIN') or conf['warmup_api'],
            'conference': {'name': conf['name'], 'date': conf['date'], 'timezone': conf['timezone'], 'miniconfUrl': conf['miniconf_url'], 'officialSiteUrl': conf['official_site_url'], 'slackAppName': conf['slack_app_name']},
        }
        texts['public-site-config.js'] = ('window.ISMIR_PUBLIC_CONFIG = Object.assign(' + json.dumps(config, ensure_ascii=False)
                                          + ", { fallbackUrl: new URL('schedule-snapshot.json', document.currentScript.src).href });\n")
        # snapshot() drops every link, so raw Zoom live_url never reaches the static site.
        texts['schedule-snapshot.json'] = json.dumps(snapshot(schedule), ensure_ascii=False, indent=2) + '\n'
        version = content_version(texts)
        for name, text in texts.items():
            if name == 'index.html':
                page = render_page(text, ASSET_DIR + '/', '', version)
                (stage / PAGE).write_text(page, encoding='utf-8')
                (stage / DEBUG_PAGE).write_text(debug_page(page), encoding='utf-8')
            else:
                (assets / name).write_text(render_page(text, './', '../' + PAGE, version) if name.endswith('.html') else text, encoding='utf-8')

        (out / PAGE).unlink(missing_ok=True)
        (out / DEBUG_PAGE).unlink(missing_ok=True)
        shutil.rmtree(out / ASSET_DIR, ignore_errors=True)
        shutil.move(str(stage / PAGE), out / PAGE)
        shutil.move(str(stage / DEBUG_PAGE), out / DEBUG_PAGE)
        shutil.move(str(assets), out / ASSET_DIR)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--mockup', action='store_true', help='Read ../sitedata_mock instead of ../sitedata (never syncs the backend)')
    parser.add_argument('--data', help='Explicit data_path (overrides --mockup; never syncs the backend)')
    parser.add_argument('--out', default=str(ROOT / 'build'))
    parser.add_argument('--api-origin', help='Backend origin (default: $LIVE_OVERVIEW_API_ORIGIN, else live_overview_api in config.yml)')
    args = parser.parse_args()
    data_path = (Path(args.data) if args.data else REPO / ('sitedata_mock' if args.mockup else 'sitedata')).resolve()

    conf = read_config(data_path / 'config.yml')
    args.api_origin = (args.api_origin or os.environ.get('LIVE_OVERVIEW_API_ORIGIN') or conf['live_overview_api']).rstrip('/')
    parts = urlsplit(args.api_origin)
    if parts.scheme != 'https' or not parts.netloc or parts.path or parts.query or parts.fragment:
        parser.error('API origin must be an HTTPS origin without a path (set live_overview_api in config.yml)')
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
