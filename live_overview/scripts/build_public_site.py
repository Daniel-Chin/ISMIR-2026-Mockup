#!/usr/bin/env python3
"""Standalone GitHub Pages exporter of the public page (no backend, credentials or Observer files).

Not part of the miniconf build, which imports only PUBLIC_RELEASE, ASSETS and snapshot().
Kept for the backend maintainer's standalone deploys.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import shutil
import tempfile
from urllib.parse import urlsplit
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_RELEASE = '1.0.0-ui.9'
ASSETS = ('index.html', 'history.html', 'app.js', 'history.js', 'styles.css',
          'timezone-preference.js', 'cursor-avatars.js', 'theme-toggle.js', 'public-connection.js', 'prompt-config.js', 'llm-prompts.json',
          'site-integration.js')
EVENT_FIELDS = ('id', 'type', 'title', 'topic', 'summary', 'organiser', 'startsAt', 'endsAt', 'day',
                'dayNumber', 'track', 'category', 'spotlight', 'sessionNumber', 'posterSessionNumber', 'paperRange', 'endTimeTBD')
PAPER_FIELDS = ('id', 'displayId', 'sourcePaperId', 'detailUrl', 'title', 'authors', 'primaryAuthor', 'abstract', 'subjects', 'isTismir', 'longPresentation',
                'presenterMode', 'funFact', 'sessionId', 'sessionNumber', 'posterSessionNumber', 'sessionPaperNumber')
CONF_FIELDS = ('name', 'location', 'theme', 'timeZone', 'startsOn', 'endsOn', 'pageTitle', 'subtitle')


def snapshot(schedule):
    now = datetime.now(timezone.utc).isoformat()
    def item(source, fields):
        # Static fallback contains metadata only, never live data or meeting links.
        result = {key: source[key] for key in fields if key in source}
        result['headcounts'] = {'zoom': 0, 'available': False, 'partial': False}
        result['metrics'] = {'available': False}
        result['links'] = {}
        return result
    events = []
    for e in schedule.get('events', []):
        if e.get('debugOnly'):
            continue
        result = item(e, EVENT_FIELDS)
        result['papers'] = [item(p, PAPER_FIELDS) for p in e.get('papers', [])]
        events.append(result)
    return {'schemaVersion': 3, 'version': 0, 'updatedAt': now, 'serverNow': now, 'offline': True,
            'conference': {k: schedule.get('conference', {}).get(k) for k in CONF_FIELDS if k in schedule.get('conference', {})},
            'debugClock': {'enabled': False, 'revision': 0}, 'events': events}


def build(output, api_origin, schedule=None, domain=''):
    parts = urlsplit(api_origin)
    if parts.scheme != 'https' or not parts.netloc or parts.path or parts.query or parts.fragment or parts.username:
        raise ValueError('--api-origin must be an HTTPS origin, without a path or trailing slash')
    if domain and not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9.-]*[a-zA-Z0-9])?', domain):
        raise ValueError('--domain must be a hostname, without https:// or a path')
    output = Path(output).resolve()
    allowed = set(ASSETS) | {'public-site-config.js', 'schedule-snapshot.json', '.nojekyll', '.ismir-public-export', 'README.md', 'CNAME'}
    if output.exists() and (not (output / '.ismir-public-export').is_file() or any(p.name not in allowed or not p.is_file() or p.is_symlink() for p in output.iterdir())):
        raise ValueError('Output must be a new directory or an unchanged export directory; refusing to overwrite other files')
    data = json.loads(Path(schedule).read_text()) if schedule else {'conference': {'name': 'ISMIR 2026', 'timeZone': 'Asia/Dubai'}, 'events': []}
    if not isinstance(data.get('events'), list) or not isinstance(data.get('conference'), dict):
        raise ValueError('Invalid schedule JSON')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ismir-public-build-', dir=output.parent) as tmp:
        stage = Path(tmp)
        for name in ASSETS:
            text = (ROOT / 'overview-source' / name).read_text()
            if name.endswith('.js'):
                text = re.sub(r"const ISMIR_BUILD_VERSION = '[^']+';", f"const ISMIR_BUILD_VERSION = '{PUBLIC_RELEASE}';", text)
            if name.endswith('.html'):
                text = re.sub(r'(\.js|\.css)\?v=[^\"\s]+', lambda m: m.group(1) + '?v=' + PUBLIC_RELEASE, text)
                text = re.sub(r'(data-build-version>)[^<]*', lambda m: m.group(1) + 'UI ' + PUBLIC_RELEASE, text)
                # Project Pages (/repository/) and a custom domain use the same files.
                text = re.sub(r'(src|href)="/(?!/)', r'\1="./', text)
                if name == 'index.html':
                    text = re.sub(r'    try \{\s*const params = new URLSearchParams\(location.search\);.*?\} catch \(error\) \{\}', '', text, flags=re.S)
                    text = re.sub(r'  <section class="debug-clock-panel".*?</section>', '', text, flags=re.S)
            (stage / name).write_text(text)
        config = {'staticHosting': True, 'apiOrigin': api_origin, 'fallbackUrl': './schedule-snapshot.json'}
        (stage / 'public-site-config.js').write_text('window.ISMIR_PUBLIC_CONFIG = ' + json.dumps(config) + ';\n')
        (stage / 'schedule-snapshot.json').write_text(json.dumps(snapshot(data), ensure_ascii=False, indent=2) + '\n')
        (stage / '.nojekyll').touch()
        (stage / '.ismir-public-export').write_text(PUBLIC_RELEASE + '\n')
        if domain:
            (stage / 'CNAME').write_text(domain + '\n')
        (stage / 'README.md').write_text('# ISMIR Overview\n\nGitHub Settings → Pages → Deploy from a branch → main / (root).\nUse the default https://USERNAME.github.io/REPOSITORY/ address. Leave Custom domain empty.\nUpload these files to the repository root, including .nojekyll.\nLive data comes from the configured backend; schedule-snapshot.json is an offline fallback without Zoom links or live telemetry.\n')
        if not schedule:
            with (stage / 'README.md').open('a') as f:
                f.write('\nThis export has NO bundled conference schedule: it loads the real schedule from the backend. For a first-visit fallback, rebuild on the server with --schedule /opt/ismir-live/data/schedule.json. No sample schedule is published.\n')
        if output.exists():
            shutil.rmtree(output)
        shutil.copytree(stage, output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-origin', default='https://live-api.liweilin.org')
    parser.add_argument('--schedule', help='Deployed schedule JSON for an optional metadata-only fallback')
    parser.add_argument('--output', default=str(ROOT / 'dist' / 'public'))
    parser.add_argument('--domain', default='', help='Optional custom domain; configure Pages settings and DNS separately')
    parser.add_argument('--zip', dest='zip_path', help='Optional ZIP of only the exported directory contents')
    args = parser.parse_args()
    output = build(args.output, args.api_origin, args.schedule, args.domain)
    if args.zip_path:
        archive = Path(args.zip_path).resolve()
        if archive == output or output in archive.parents:
            parser.error('ZIP must be outside the output directory')
        archive.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as z:
            for p in sorted(output.iterdir()):
                z.write(p, p.name)
        print('Public-only ZIP: ' + str(archive))
    print('Public-only directory: ' + str(output))
    print('No backend code, Observer pages, OAuth credentials or runtime data were exported.')


if __name__ == '__main__':
    main()
