'''
Reads a CSV downloaded from the results of Google Form and fills papers.csv,
then, after confirmation, the same cells of the Live Database papers tab.
The implementation should change every year, unless they decided to standardize the Google Form.
uv run python -m scripts.parse_google_form_author_uploaded_materials --input $csv_path
'''

import argparse
import csv
import re
from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path
from pprint import pprint

from utils.live_database import SHEETS_SCOPE, CellChange, google_credentials, update_papers_tab

INPUT_PATH = '~/ismir2026/uploaded_mats.csv'  # Use your own path
MAX_PAPER_ID = 800
# The export's timestamp format follows the exporting Google account's locale:
# '09/21/2026 14:12:59', or '2026/09/21 2:12:59 PM GMT+4' (the zone is the same for every row: dropped).
TIMESTAMP_FORMATS = ('%m/%d/%Y %H:%M:%S', '%Y/%m/%d %I:%M:%S %p')

OUTPUT_PATH = '../sitedata/papers.csv'
# Changes to these columns need the downloader (and YouTube) to run for their papers.
VIDEO_COLUMNS = ('raw_video', 'raw_captions')


def parse_timestamp(value: str) -> datetime:
    value = value.split(' GMT')[0].strip()
    for timestamp_format in TIMESTAMP_FORMATS:
        try:
            return datetime.strptime(value, timestamp_format)
        except ValueError:
            pass
    raise ValueError(f'Unknown timestamp format: {value!r}')


def squeezed(text: str) -> str:
    """For comparing a sheet cell with a submission: a paste into the sheet can change the whitespace."""
    return ' '.join(text.split())


def parse_optional_text(value: str) -> str | None:
    return value or None


def parse_drive_url(value: str) -> str | None:
    """One link per uploaded file, whatever form the export writes it in ('open?id=X',
    'u/0/open?usp=forms_web&id=X', 'file/d/X/view'), so that a cell in papers.csv holding an earlier
    submission is recognised as one, and not mistaken for a manual edit that blocks a new upload."""
    if not value:
        return None
    match = re.search(r'[?&]id=([\w-]+)', value) or re.search(r'/file/d/([\w-]+)', value)
    return f'https://drive.google.com/open?id={match.group(1)}' if match and 'drive.google.com' in value else value


@dataclass(frozen=True)
class AuthorUploadedMaterials:
    timestamp: datetime = field(metadata={'header': 'Timestamp', 'parse': parse_timestamp}) # no timezone info; non-critical
    paper_id: int = field(metadata={'header': 'Paper ID', 'parse': int})
    poster_url: str | None = field(metadata={'header': 'poster', 'output': 'raw_poster_pdf', 'parse': parse_drive_url})
    thumbnail_url: str | None = field(metadata={'header': 'thumbnail', 'output': 'raw_thumbnail', 'parse': parse_drive_url})
    video_url: str | None = field(metadata={'header': 'video presentation', 'output': 'raw_video', 'parse': parse_drive_url})
    captions_url: str | None = field(metadata={'header': 'captions', 'output': 'raw_captions', 'parse': parse_drive_url})
    fun_facts: str | None = field(metadata={'header': 'fun facts', 'output': 'fun_facts'})


# paper_id -> field name -> every value ever submitted for it
History = dict[int, dict[str, set[str]]]


def parse_materials(path: str | Path = INPUT_PATH) -> tuple[dict[int, AuthorUploadedMaterials], History]:
    """Fail fast on unexpected exports; blank material cells become None.
    Also returns the history of submitted values, so that manual edits in papers.csv can be told apart."""
    material_fields = fields(AuthorUploadedMaterials)
    field_names = {item.name for item in material_fields}
    header_map = {item.metadata['header']: item.name for item in material_fields}
    parsers = {item.name: item.metadata.get('parse', parse_optional_text) for item in material_fields}

    papers: dict[int, AuthorUploadedMaterials] = {}
    history: History = {}
    with Path(path).expanduser().open(newline='', encoding='utf-8-sig') as source:
        reader = csv.reader(source, strict=True)
        headers = next(reader, None)
        if not headers:
            raise ValueError('Missing CSV header')
        columns: list[str | None] = []
        for header_cell in headers:
            matches = [name for header, name in header_map.items() if header in header_cell]
            if len(matches) == 0:
                print(f'Info: discarding column "{header_cell[:40]}".')
                columns.append(None)
                continue
            if len(matches) >= 2:
                raise ValueError(f'Expected one header match for {header_cell!r}, got {matches}')
            if matches[0] in columns:
                raise ValueError(f'Duplicate column for {matches[0]!r}')
            columns.append(matches[0])
        if missing := field_names - set(columns):
            raise ValueError(f'Missing columns: {sorted(missing)}')

        for row in reader:
            if len(row) != len(columns):
                raise ValueError(f'CSV line {reader.line_num}: expected {len(columns)} cells, got {len(row)}')
            try:
                values = {name: parsers[name](cell.strip())
                          for name, cell in zip(columns, row) if name is not None}
            except (ValueError, TypeError) as exc:
                raise ValueError(f'CSV line {reader.line_num}: invalid timestamp or paper ID') from exc
            current = AuthorUploadedMaterials(**values)
            if current.paper_id <= 0:
                raise ValueError(f'CSV line {reader.line_num}: nonpositive paper ID {current.paper_id}')
            if current.paper_id > MAX_PAPER_ID:
                print(f'Warning: paper_id {current.paper_id} > MAX_PAPER_ID ({MAX_PAPER_ID})')
                input('Is it a test submission? Press Enter to DISCARD this paper...')
                continue

            paper_history = history.setdefault(current.paper_id, {})
            for name in field_names:
                if isinstance(value := getattr(current, name), str):
                    paper_history.setdefault(name, set()).add(value)

            previous = papers.get(current.paper_id)
            if previous is not None:
                if current.timestamp == previous.timestamp:
                    raise ValueError(f'Paper {current.paper_id}: repeated timestamp {current.timestamp}')
                newer, older = sorted((current, previous), key=lambda entry: entry.timestamp, reverse=True)
                current = AuthorUploadedMaterials(**{
                    name: getattr(newer, name) if getattr(newer, name) is not None else getattr(older, name)
                    for name in field_names
                })
            papers[current.paper_id] = current

    if not papers:
        raise ValueError('CSV contains no submissions')
    for paper_id, materials in papers.items():
        missing_values = sorted(name for name in field_names
                         if name != 'fun_facts' and getattr(materials, name) is None)
        assert not missing_values, f'Paper {paper_id}: missing required values: {missing_values}'
    return papers, history


def debug():
    for paper_id, materials in parse_materials()[0].items():
        print(paper_id)
        pprint(materials)
        input('Enter...')


def write_into_sitedata(papers: dict[int, AuthorUploadedMaterials], history: History) -> list[CellChange]:
    """Priority: manual edits in papers.csv > later submissions > earlier submissions.
    A nonblank cell that matches no past submission is assumed to be a manual edit and is kept.
    Returns the cells it changed."""
    output_path = (Path(__file__).resolve().parent / OUTPUT_PATH).resolve()
    output_map = {item.name: item.metadata['output'] for item in fields(AuthorUploadedMaterials)
                  if 'output' in item.metadata}
    with output_path.open(newline='', encoding='utf-8') as source:
        reader = csv.reader(source, strict=True)
        headers = next(reader, None)
        if not headers or len(headers) != len(set(headers)):
            raise ValueError('Missing or duplicate output CSV headers')
        if 'uid' not in headers:
            raise ValueError('Missing output column: uid')
        added = [column for column in output_map.values() if column not in headers]
        if added:
            print(f'Info: adding new output columns {added}.')
        n_cells = len(headers)
        headers += added
        uid_index = headers.index('uid')
        output_columns = {name: headers.index(column) for name, column in output_map.items()}
        rows: list[list[str]] = []
        changes: list[CellChange] = []
        seen: set[int] = set()
        for row in reader:
            if len(row) != n_cells:
                raise ValueError(f'Output CSV line {reader.line_num}: expected {n_cells} cells, got {len(row)}')
            row += [''] * len(added)
            paper_id = int(row[uid_index])
            if paper_id <= 0 or paper_id in seen:
                raise ValueError(f'Invalid or duplicate output paper ID: {paper_id}')
            seen.add(paper_id)
            if paper_id in papers:
                materials = papers[paper_id]
                if materials.paper_id != paper_id:
                    raise ValueError(f'Paper ID does not match dictionary key: {paper_id}')
                for name, index in output_columns.items():
                    value = getattr(materials, name)
                    existing = row[index].strip()
                    if value is None or squeezed(existing) == squeezed(value):
                        continue
                    if not existing or squeezed(existing) in map(squeezed, history[paper_id].get(name, ())):
                        changes.append(CellChange(str(paper_id), output_map[name], row[index], value))
                        row[index] = value
                    else:
                        print(f'Info: paper {paper_id} {output_map[name]}: keeping manual value {existing!r} '
                              f'over submitted {value!r}')
            rows.append(row)
    if unknown := papers.keys() - seen:
        raise ValueError(f'Submitted paper IDs missing from output CSV: {sorted(unknown)}')
    if not_submitted := seen - papers.keys():
        print(f'Warning: {len(not_submitted)} paper IDs in output CSV have no submission: '
              f'[{",".join(map(str, sorted(not_submitted)))}]')

    with output_path.open('w', newline='', encoding='utf-8') as destination:
        writer = csv.writer(destination)
        writer.writerow(headers)
        writer.writerows(rows)
    print(f'Author materials updated in {output_path}: {len(changes)} cells.')
    for column in output_map.values():
        uids = [change.uid for change in changes if change.column == column]
        print(f'  {column}: {len(uids)} [{",".join(uids)}]')
    if uids := sorted({change.uid for change in changes if change.column in VIDEO_COLUMNS}, key=int):
        print(f'New videos or captions; next: uv run python -m scripts.download_and_rename_videos_and_captions --uids {",".join(uids)}')
    return changes

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=INPUT_PATH, help='Google Form results CSV path')
    parser.add_argument('--no-sheet', action='store_true', help='Only update the local papers.csv')
    args = parser.parse_args()
    changes = write_into_sitedata(*parse_materials(args.input))
    if changes and not args.no_sheet:
        update_papers_tab(changes, google_credentials([SHEETS_SCOPE]))
