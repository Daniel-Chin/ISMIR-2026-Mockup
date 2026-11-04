'''Copy a sitedata CSV to the clipboard as TSV, for pasting into a Google Sheet tab.'''

import csv
import io
from pathlib import Path

import pyperclip

SITEDATA = Path('./sitedata')


def choose_csv() -> Path:
    paths = sorted(SITEDATA.rglob('*.csv'))
    for index, path in enumerate(paths, 1):
        print(f'{index:3d}. {path.relative_to(SITEDATA)}')
    while True:
        choice = input('Which file? ').strip()
        if choice.isdigit() and 1 <= int(choice) <= len(paths):
            return paths[int(choice) - 1]
        print(f'Enter a number from 1 to {len(paths)}.')


def copy_csv(path: Path) -> None:
    """As TSV with quoted multi-line cells, which Google Sheets parses on paste, keeping the newlines."""
    with path.open(newline='', encoding='utf-8') as source:
        rows = list(csv.reader(source))
    buffer = io.StringIO()
    csv.writer(buffer, dialect='excel-tab').writerows(rows)
    pyperclip.copy(buffer.getvalue())
    print(f'Copied {len(rows)} rows (with header) of {path}. Paste into cell A1.')


if __name__ == '__main__':
    copy_csv(choose_csv())
