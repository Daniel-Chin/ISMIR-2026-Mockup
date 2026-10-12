'''
Check if posters are roughly 1:1.414 landscape.
1. Download all poster PDFs to `POSTERS_DIR`
2. Run this.
'''

import argparse
import csv
import html
import json
import math
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

POSTERS_DIR = './tmp/posters/all'
PAPERS_CSV = './sitedata/papers.csv'
CACHE_PATH = Path('./tmp/poster_drive_names.json')

TARGET_RATIO = math.sqrt(2)  # width / height
TOLERANCE = 0.15  # relative


def page_sizes(path: Path) -> list[tuple[float, float]]:
    '''Return (width, height) in pts of each page, accounting for rotation.'''
    result = subprocess.run(
        ['pdfinfo', '-f', '1', '-l', '-1', str(path)],
        capture_output=True, text=True, check=True,
    )
    sizes = re.findall(r'^Page\s+\d+ size:\s+([\d.]+) x ([\d.]+)', result.stdout, re.MULTILINE)
    rots = re.findall(r'^Page\s+\d+ rot:\s+(\d+)', result.stdout, re.MULTILINE)
    out = []
    for (w, h), rot in zip(sizes, rots):
        w, h = float(w), float(h)
        if int(rot) % 180 == 90:
            w, h = h, w
        out.append((w, h))
    return out


def drive_file_id(url: str) -> str | None:
    parsed = urlparse(url.strip())
    if 'drive.google.com' not in parsed.netloc:
        return None
    if file_id := parse_qs(parsed.query).get('id', [None])[0]:
        return file_id
    match = re.search(r'/d/([\w-]+)', parsed.path)
    return match.group(1) if match else None


def drive_file_name(file_id: str) -> str:
    '''Name of a public Google Drive file, scraped from its view page title.'''
    response = requests.get(f'https://drive.google.com/file/d/{file_id}/view', timeout=60)
    response.raise_for_status()
    match = re.search(r'<title>(.*?)</title>', response.text, re.DOTALL)
    if match is None:
        raise ValueError(f'No title found for Drive file {file_id}')
    return html.unescape(match.group(1)).strip().removesuffix(' - Google Drive')


def check(path: Path, tolerance: float) -> list[str]:
    '''Return the problems of one poster PDF.'''
    try:
        sizes = page_sizes(path)
    except subprocess.CalledProcessError as exc:
        return [f'failed to read: {exc.stderr.strip()}']
    problems = []
    if len(sizes) != 1:
        problems.append(f'{len(sizes)} pages')
    if sizes:
        w, h = sizes[0]
        ratio = w / h
        if ratio < 1:
            problems.append('portrait')
        if abs(ratio - TARGET_RATIO) / TARGET_RATIO > tolerance:
            problems.append(f'ratio {ratio:.3f} (w/h)')
    return problems


def drive_file_names(file_ids: list[str]) -> dict[str, str]:
    '''Return {file_id: name}. Drive files are immutable, so names are cached forever.'''
    cache = json.loads(CACHE_PATH.read_text()) if CACHE_PATH.exists() else {}
    if todo := sorted(set(file_ids) - cache.keys()):
        print(f'Querying Google Drive for {len(todo)} poster names...')
        with ThreadPoolExecutor(max_workers=16) as pool:
            cache.update(zip(todo, pool.map(drive_file_name, todo)))
        CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        CACHE_PATH.write_text(json.dumps(cache, indent=1, sort_keys=True))
    return cache


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--posters', type=Path, default=Path(POSTERS_DIR), help='Poster directory')
    parser.add_argument('--tolerance', type=float, default=TOLERANCE, help='Relative ratio tolerance')
    args = parser.parse_args()

    with open(PAPERS_CSV, newline='', encoding='utf-8') as f:
        uid_to_id = {
            row['uid']: file_id for row in csv.DictReader(f)
            if (file_id := drive_file_id(row['raw_poster_pdf']))
        }
    names = drive_file_names(list(uid_to_id.values()))

    print(f'Checking {len(uid_to_id)} posters in {args.posters}...')
    n_bad = 0
    for uid, file_id in uid_to_id.items():
        name = names[file_id]
        path = args.posters / name
        problems = check(path, args.tolerance) if path.exists() else ['missing local file']
        if problems:
            n_bad += 1
            print(f'paper {uid}: {name}: {", ".join(problems)}')
    print(f'{n_bad} / {len(uid_to_id)} posters flagged')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
