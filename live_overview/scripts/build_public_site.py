#!/usr/bin/env python3
"""Standalone GitHub Pages exporter of the public page (no backend, credentials or Observer files).

Not part of the miniconf build (build_miniconf.py); both ship site_files.ASSETS.
Kept for the backend maintainer's standalone deploys.
"""
import argparse
import json
from pathlib import Path
import re
import shutil
import sys
import tempfile
from urllib.parse import urlsplit
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from site_files import ASSETS, ROOT, asset_source, content_version, snapshot  # noqa: E402


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
    data = json.loads(Path(schedule).read_text(encoding='utf-8')) if schedule else {'conference': {'name': 'ISMIR', 'timeZone': 'UTC'}, 'events': []}
    if not isinstance(data.get('events'), list) or not isinstance(data.get('conference'), dict):
        raise ValueError('Invalid schedule JSON')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='ismir-public-build-', dir=output.parent) as tmp:
        stage = Path(tmp)
        texts = {name: asset_source(name).read_text(encoding='utf-8') for name in ASSETS}
        config = {'apiOrigin': api_origin, 'fallbackUrl': './schedule-snapshot.json'}
        texts['public-site-config.js'] = 'window.ISMIR_PUBLIC_CONFIG = ' + json.dumps(config) + ';\n'
        version = content_version(texts)
        for name, text in texts.items():
            if name.endswith('.html'):
                text = re.sub(r'(name="build-version" content=")[^"]*', lambda m: m.group(1) + version, text)
                # Project Pages (/repository/) and a custom domain use the same files.
                text = re.sub(r'(src|href)="/(?!/)([^"?#]*)(#[^"]*)?"',
                              lambda m: f'{m[1]}="./{m[2]}?v={version}{m[3] or ""}"' if m[2] else f'{m[1]}="./{m[3] or ""}"', text)
            (stage / name).write_text(text, encoding='utf-8')
        (stage / 'schedule-snapshot.json').write_text(json.dumps(snapshot(data), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (stage / '.nojekyll').touch()
        (stage / '.ismir-public-export').write_text(version + '\n', encoding='utf-8')
        if domain:
            (stage / 'CNAME').write_text(domain + '\n', encoding='utf-8')
        (stage / 'README.md').write_text('# ISMIR Overview\n\nGitHub Settings → Pages → Deploy from a branch → main / (root).\nUse the default https://USERNAME.github.io/REPOSITORY/ address. Leave Custom domain empty.\nUpload these files to the repository root, including .nojekyll.\nLive data comes from the configured backend; schedule-snapshot.json is an offline fallback without Zoom links or live telemetry.\n', encoding='utf-8')
        if not schedule:
            with (stage / 'README.md').open('a', encoding='utf-8') as f:
                f.write('\nThis export has NO bundled conference schedule: it loads the real schedule from the backend. For a first-visit fallback, rebuild on the server with --schedule /opt/ismir-live/data/schedule.json. No sample schedule is published.\n')
        if output.exists():
            shutil.rmtree(output)
        shutil.copytree(stage, output)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-origin', required=True, help='Backend origin, e.g. https://live-api.example.org')
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
