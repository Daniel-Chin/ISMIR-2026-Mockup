'''
Check if posters are roughly 1:1.414 landscape.
1. Download all poster PDFs to `IN_DIR`
2. Run this.
'''

import argparse
import csv
import html
import math
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import requests

IN_DIR = './tmp/posters/all'
PAPERS_CSV = './sitedata/papers.csv'

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


def poster_name_to_uids() -> dict[str, list[str]]:
    '''Return {poster PDF name on Google Drive: [paper_id, ...]}.'''
    with open(PAPERS_CSV, newline='', encoding='utf-8') as f:
        uid_to_id = {
            row['uid']: file_id for row in csv.DictReader(f)
            if (file_id := drive_file_id(row['raw_poster_pdf']))
        }
    with ThreadPoolExecutor(max_workers=16) as pool:
        names = pool.map(drive_file_name, uid_to_id.values())
    name_to_uids: dict[str, list[str]] = {}
    for uid, name in zip(uid_to_id, names):
        name_to_uids.setdefault(name, []).append(uid)
    return name_to_uids


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--posters', type=Path, default=Path(IN_DIR), help='Poster directory')
    parser.add_argument('--tolerance', type=float, default=TOLERANCE, help='Relative ratio tolerance')
    args = parser.parse_args()

    posters = sorted(args.posters.glob('*.pdf'))
    print(f'Checking {len(posters)} posters in {args.posters}...')
    flagged: list[tuple[str, list[str]]] = []
    for path in posters:
        try:
            sizes = page_sizes(path)
        except subprocess.CalledProcessError as exc:
            flagged.append((path.name, [f'failed to read: {exc.stderr.strip()}']))
            continue
        problems = []
        if len(sizes) != 1:
            problems.append(f'{len(sizes)} pages')
        if sizes:
            w, h = sizes[0]
            ratio = w / h
            if ratio < 1:
                problems.append('portrait')
            if abs(ratio - TARGET_RATIO) / TARGET_RATIO > args.tolerance:
                problems.append(f'ratio {ratio:.3f} (w/h)')
        if problems:
            flagged.append((path.name, problems))
    if flagged:
        print(f'Querying Google Drive for poster names in {PAPERS_CSV}...')
        name_to_uids = poster_name_to_uids()
        for name, problems in flagged:
            uids = ', '.join(name_to_uids.get(name, ['?']))
            print(f'paper {uids}: {name}: {", ".join(problems)}')
    print(f'{len(flagged)} / {len(posters)} posters flagged')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
