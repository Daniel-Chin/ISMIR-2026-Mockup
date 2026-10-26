'''
Reads a CSV downloaded from the results of Google Form and fills papers.csv  
The implementation should change every year, unless they decided to standardize the Google Form.  
'''

import argparse
import csv
import io
from dataclasses import dataclass, field, fields
from datetime import datetime
from pathlib import Path
from pprint import pprint

import pyperclip

INPUT_PATH = '~/ismir2026/uploaded_mats.csv'  # Use your own path
MAX_PAPER_ID = 800
TIMESTAMP_FORMAT = '%m/%d/%Y %H:%M:%S'

OUTPUT_PATH = '../sitedata/papers.csv'


def parse_timestamp(value: str) -> datetime:
    return datetime.strptime(value, TIMESTAMP_FORMAT)


def parse_optional_text(value: str) -> str | None:
    return value or None


@dataclass(frozen=True)
class AuthorUploadedMaterials:
    timestamp: datetime = field(metadata={'header': 'Timestamp', 'parse': parse_timestamp}) # no timezone info; non-critical
    paper_id: int = field(metadata={'header': 'Paper ID', 'parse': int})
    poster_url: str | None = field(metadata={'header': 'poster', 'output': 'raw_poster_pdf'})
    thumbnail_url: str | None = field(metadata={'header': 'thumbnail', 'output': 'raw_thumbnail'})
    video_url: str | None = field(metadata={'header': 'video presentation', 'output': 'raw_video'})
    captions_url: str | None = field(metadata={'header': 'captions', 'output': 'raw_captions'})
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


def write_into_sitedata(papers: dict[int, AuthorUploadedMaterials], history: History) -> None:
    """Priority: manual edits in papers.csv > later submissions > earlier submissions.
    A nonblank cell that matches no past submission is assumed to be a manual edit and is kept."""
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
                    if value is None or existing == value:
                        continue
                    if not existing or existing in history[paper_id].get(name, ()):
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
    print(f'Author materials updated in {output_path}.')
    print(f'Please paste the updated {", ".join(output_map.values())} columns back into the Google Sheet '
          'papers tab before running pull_from_google_sheet.py.')
    for column in output_map.values():
        if input(f'Copy {column} (with header, in papers.csv row order) to the clipboard? [y/N] ').strip().lower() == 'y':
            copy_column(headers, rows, column)


def copy_column(headers: list[str], rows: list[list[str]], column: str) -> None:
    """With quoted multi-line cells, which Google Sheets parses on paste, keeping the newlines."""
    index = headers.index(column)
    buffer = io.StringIO()
    writer = csv.writer(buffer, dialect='excel-tab')
    writer.writerow([column])
    writer.writerows([row[index]] for row in rows)
    pyperclip.copy(buffer.getvalue())
    print(f'Copied. Paste into the {column} header cell.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=INPUT_PATH, help='Google Form results CSV path')
    write_into_sitedata(*parse_materials(parser.parse_args().input))
