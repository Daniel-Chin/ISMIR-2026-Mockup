'''Symlink opted-in-to-print poster PDFs as tmp/posters_to_print/P{xx}-{yy}_First_Three_Words.pdf'''

import csv
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PRINTING_CSV = Path('./local/printing.csv')
PAPERS_CSV = Path('./sitedata/papers.csv')
LBDS_CSV = Path('./sitedata/lbds.csv')
DRIVE_NAMES = Path('./tmp/poster_drive_names.json')
POSTERS_DIR = Path('./tmp/posters/all')
OUT_DIR = Path('./tmp/posters_to_print')


def main():
    papers = {p['uid']: p for csv_path in (LBDS_CSV, PAPERS_CSV) for p in csv.DictReader(csv_path.open())}
    drive_names = json.loads(DRIVE_NAMES.read_text())
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for old in OUT_DIR.iterdir():
        old.unlink()
    seen = set()
    for row in csv.DictReader(PRINTING_CSV.open()):
        uid = row['Please fill one CMT Paper ID.'].strip()
        if row['Do you request Printing Service for this paper?'].strip() != 'Yes' or uid in seen:
            continue
        seen.add(uid)
        paper = papers.get(uid)
        if paper is None:
            print(f'{uid}: not in papers.csv nor lbds.csv')
            continue
        file_id = parse_qs(urlparse(paper['raw_poster_pdf']).query).get('id', [None])[0]
        src = POSTERS_DIR / drive_names.get(file_id, '').replace('/', '_')  # as Drive's zip download does
        if not file_id or not src.is_file():
            print(f'{uid}: poster PDF not found locally ({paper["raw_poster_pdf"]!r})')
            continue
        if session_slot := re.match(r'p(\d+)-(\d+)-', paper['slack_channel']):
            code = 'P{:02d}-{:02d}'.format(*map(int, session_slot.groups()))
        else:
            code = f'LBD{uid}'
        words = re.findall(r'[\w]+', paper['title'])[:3]
        dst = OUT_DIR / f'{code}_{"_".join(words)}.pdf'
        dst.symlink_to(src.resolve())
    print(f'{len(list(OUT_DIR.iterdir()))} links in {OUT_DIR}')


if __name__ == '__main__':
    main()
