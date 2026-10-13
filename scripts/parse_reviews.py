'''
Reads the reviews and meta-reviews CSVs exported from the review system and fills review1-4 / meta_review in papers.csv.
Refuses to touch papers whose publish_reviews is not true.
uv run python ./scripts/parse_reviews.py
'''

import csv
import io
import re
from pathlib import Path

import pyperclip

REVIEWS_FILE = '~/ismir2026/reviews.csv'
META_REVIEWS_FILE = '~/ismir2026/meta_reviews.csv'
OUT_FILE = './sitedata/papers.csv'

N_REVIEWERS = 4
REVIEW_COLUMNS = [f'review{i}' for i in range(1, N_REVIEWERS + 1)] + ['meta_review']
# Question numbers to bold instead of italicize (the main review text). Check against the review form every year.
BOLD_QUESTIONS = {'Q23'}


def parse_bool(value: str) -> bool:
    match value.strip().lower():
        case 'true' | 'yes':
            return True
        case 'false' | 'no':
            return False
    raise ValueError(f'Invalid boolean: {value!r}')


def out_path() -> Path:
    return (Path(__file__).resolve().parent.parent / OUT_FILE).resolve()


def load_publish_reviews() -> dict[int, bool]:
    with out_path().open(newline='', encoding='utf-8') as source:
        return {int(row['uid']): parse_bool(row['publish_reviews']) for row in csv.DictReader(source, strict=True)}


def format_question(header: str) -> str:
    """'Q2 ( I am an expert.)' -> 'Q2. I am an expert.'"""
    if not (match := re.fullmatch(r'(Q\d+) \((.*)\)', header.strip(), re.DOTALL)):
        raise ValueError(f'Unexpected question header: {header!r}')
    return f'{match[1]}. {match[2].strip()}'


def emphasize(question: str) -> str:
    marker = '**' if question.split('.', 1)[0] in BOLD_QUESTIONS else '*'
    return f'{marker}{question}{marker}'


def format_review(questions: list[str], answers: list[str]) -> str:
    return '\n\n'.join(f'{emphasize(q)}\n\n{a}' for q, a in zip(questions, answers, strict=True))


def parse_file(path: str, has_reviewer_number: bool, publish: dict[int, bool]) -> dict[int, dict[str, str]]:
    """paper_id -> output column -> formatted review"""
    papers: dict[int, dict[str, str]] = {}
    with Path(path).expanduser().open(newline='', encoding='utf-8-sig') as source:
        reader = csv.reader(source, strict=True)
        headers = next(reader, None)
        expected = ['Paper ID', 'Paper Title'] + (['Reviewer Number'] if has_reviewer_number else [])
        if not headers or headers[:len(expected)] != expected:
            raise ValueError(f'{path}: expected headers to start with {expected}, got {headers}')
        questions = [format_question(header) for header in headers[len(expected):]]
        for row in reader:
            if len(row) != len(headers):
                raise ValueError(f'{path} line {reader.line_num}: expected {len(headers)} cells, got {len(row)}')
            paper_id = int(row[0])
            if paper_id not in publish:
                raise ValueError(f'{path}: paper {paper_id} missing from output CSV')
            if not publish[paper_id]:
                raise ValueError(f'{path}: paper {paper_id} has publish_reviews=FALSE but has a review')
            if has_reviewer_number:
                reviewer = int(row[2])
                if not 1 <= reviewer <= N_REVIEWERS:
                    raise ValueError(f'{path}: paper {paper_id} invalid reviewer number {reviewer}')
                column = f'review{reviewer}'
            else:
                column = 'meta_review'
            reviews = papers.setdefault(paper_id, {})
            if column in reviews:
                raise ValueError(f'{path}: paper {paper_id} duplicate {column}')
            reviews[column] = format_review(questions, row[len(expected):])
    return papers


def parse_reviews() -> dict[int, dict[str, str]]:
    publish = load_publish_reviews()
    papers = parse_file(REVIEWS_FILE, True, publish)
    for paper_id, reviews in parse_file(META_REVIEWS_FILE, False, publish).items():
        papers.setdefault(paper_id, {}).update(reviews)
    return papers


def write_into_sitedata(papers: dict[int, dict[str, str]]) -> None:
    output_path = out_path()
    with output_path.open(newline='', encoding='utf-8') as source:
        reader = csv.reader(source, strict=True)
        headers = next(reader, None)
        if not headers or len(headers) != len(set(headers)):
            raise ValueError('Missing or duplicate output CSV headers')
        if missing := ({'uid', 'publish_reviews'} | set(REVIEW_COLUMNS)) - set(headers):
            raise ValueError(f'Missing output columns: {sorted(missing)}')
        uid_index = headers.index('uid')
        publish_index = headers.index('publish_reviews')
        rows: list[list[str]] = []
        seen: set[int] = set()
        for row in reader:
            if len(row) != len(headers):
                raise ValueError(f'Output CSV line {reader.line_num}: expected {len(headers)} cells, got {len(row)}')
            paper_id = int(row[uid_index])
            if paper_id in seen:
                raise ValueError(f'Duplicate output paper ID: {paper_id}')
            seen.add(paper_id)
            reviews = papers.get(paper_id, {})
            if reviews and not parse_bool(row[publish_index]):
                raise ValueError(f'Paper {paper_id}: publish_reviews is not TRUE')
            for column, value in reviews.items():
                index = headers.index(column)
                existing = row[index].strip()
                if existing and existing != value.strip():
                    raise ValueError(f'Paper {paper_id} {column}: existing value differs from new value')
                row[index] = value
            rows.append(row)
    if unknown := papers.keys() - seen:
        raise ValueError(f'Input paper IDs missing from output CSV: {sorted(unknown)}')

    with output_path.open('w', newline='', encoding='utf-8') as destination:
        writer = csv.writer(destination)
        writer.writerow(headers)
        writer.writerows(rows)
    print(f'Reviews updated in {output_path}.')
    print(f'Please paste the updated {", ".join(REVIEW_COLUMNS)} columns back into the Google Sheet '
          'papers tab before running pull_from_google_sheet.py.')
    if input('Copy those columns (with header, in papers.csv row order) to the clipboard? [y/N] ').strip().lower() == 'y':
        copy_columns(headers, rows)


def copy_columns(headers: list[str], rows: list[list[str]]) -> None:
    """As TSV with quoted multi-line cells, which Google Sheets parses on paste, keeping the newlines."""
    indices = [headers.index(column) for column in REVIEW_COLUMNS]
    buffer = io.StringIO()
    writer = csv.writer(buffer, dialect='excel-tab')
    writer.writerow(REVIEW_COLUMNS)
    writer.writerows([row[index] for index in indices] for row in rows)
    pyperclip.copy(buffer.getvalue())
    print(f'Copied. Paste into the {REVIEW_COLUMNS[0]} header cell.')


if __name__ == '__main__':
    write_into_sitedata(parse_reviews())
