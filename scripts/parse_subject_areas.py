'''
Reads the subject areas CSV exported from the review system and fills primary_subject / secondary_subject in papers.csv.
uv run python ./scripts/parse_subject_areas.py
'''

import csv
from pathlib import Path

IN_FILE = '~/ismir2026/subject_areas.csv'
OUT_FILE = './sitedata/papers.csv'

# input header -> output column
COLUMNS = {
    'Primary Subject Area': 'primary_subject',
    'Secondary Subject Areas': 'secondary_subject',
}


def normalize(value: str) -> str:
    return ';'.join(part.strip() for part in value.split(';') if part.strip())


def parse_subject_areas() -> dict[int, dict[str, str]]:
    papers: dict[int, dict[str, str]] = {}
    with Path(IN_FILE).expanduser().open(newline='', encoding='utf-8-sig') as source:
        reader = csv.DictReader(source, strict=True)
        if missing := ({'Paper ID'} | COLUMNS.keys()) - set(reader.fieldnames or ()):
            raise ValueError(f'Missing input columns: {sorted(missing)}')
        for row in reader:
            paper_id = int(row['Paper ID'])
            if paper_id in papers:
                raise ValueError(f'Duplicate input paper ID: {paper_id}')
            papers[paper_id] = {column: normalize(row[header]) for header, column in COLUMNS.items()}
    return papers


def write_into_sitedata(papers: dict[int, dict[str, str]]) -> None:
    output_path = (Path(__file__).resolve().parent.parent / OUT_FILE).resolve()
    with output_path.open(newline='', encoding='utf-8') as source:
        reader = csv.reader(source, strict=True)
        headers = next(reader, None)
        if not headers or len(headers) != len(set(headers)):
            raise ValueError('Missing or duplicate output CSV headers')
        if missing := ({'uid'} | set(COLUMNS.values())) - set(headers):
            raise ValueError(f'Missing output columns: {sorted(missing)}')
        uid_index = headers.index('uid')
        rows: list[list[str]] = []
        seen: set[int] = set()
        for row in reader:
            if len(row) != len(headers):
                raise ValueError(f'Output CSV line {reader.line_num}: expected {len(headers)} cells, got {len(row)}')
            paper_id = int(row[uid_index])
            if paper_id in seen:
                raise ValueError(f'Duplicate output paper ID: {paper_id}')
            seen.add(paper_id)
            for column, value in papers.get(paper_id, {}).items():
                index = headers.index(column)
                existing = row[index].strip()
                if existing and existing != value:
                    raise ValueError(f'Paper {paper_id} {column}: existing {existing!r} != new {value!r}')
                row[index] = value
            rows.append(row)
    if unknown := papers.keys() - seen:
        raise ValueError(f'Input paper IDs missing from output CSV: {sorted(unknown)}')
    if not_found := seen - papers.keys():
        print(f'Warning: {len(not_found)} paper IDs in output CSV have no subject areas: '
              f'[{",".join(map(str, sorted(not_found)))}]')

    with output_path.open('w', newline='', encoding='utf-8') as destination:
        writer = csv.writer(destination)
        writer.writerow(headers)
        writer.writerows(rows)
    print(f'Subject areas updated in {output_path}.')
    print(f'Please paste the updated {", ".join(COLUMNS.values())} columns back into the Google Sheet '
          'papers tab before running pull_from_google_sheet.py.')


if __name__ == '__main__':
    write_into_sitedata(parse_subject_areas())
