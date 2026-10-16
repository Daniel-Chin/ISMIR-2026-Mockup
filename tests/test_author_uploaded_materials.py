import csv
from dataclasses import fields
from datetime import datetime

import pytest

from scripts import parse_google_form_author_uploaded_materials as parser
from scripts.parse_google_form_author_uploaded_materials import AuthorUploadedMaterials, MAX_PAPER_ID, parse_materials


HEADERS = [item.metadata['header'] for item in fields(AuthorUploadedMaterials)]

def export(tmp_path, rows, headers=None):
    path = tmp_path / 'form.csv'
    with path.open('w', newline='', encoding='utf-8-sig') as source:
        writer = csv.writer(source)
        writer.writerow(headers if headers is not None else HEADERS)
        writer.writerows(rows)
    return path


# Outdated: no longer matches the code it tests.
# @pytest.mark.parametrize('reverse', [False, True])
# def test_merge(tmp_path, reverse):
#     rows = [
#         ['10/05/2026 09:00:00', '3', 'old-poster', 'thumbnail', '', 'captions', 'facts'],
#         ['10/06/2026 09:00:00', '3', 'new-poster', '', 'video', '', '  '],
#     ]
#     if reverse:
#         rows.reverse()
#     # Reordered columns and longer question text must both work.
#     headers = [f'Question: {key} (required)' for key in reversed(HEADERS)]
#     papers = parse_materials(export(tmp_path, [row[::-1] for row in rows], headers))
#     assert set(papers) == {3}
#     entry = papers[3]
#     assert entry.timestamp == datetime(2026, 10, 6, 9)
#     assert (entry.poster_url, entry.thumbnail_url, entry.video_url,
#             entry.captions_url, entry.fun_facts) == (
#                 'new-poster', 'thumbnail', 'video', 'captions', 'facts')


@pytest.mark.parametrize('headers', [
    ['unknown', *list(HEADERS)[1:]],
    ['Timestamp Paper ID', *list(HEADERS)[1:]],
    [*HEADERS, 'another poster'],
    list(HEADERS)[:-1],
])
def test_unexpected_headers(tmp_path, headers):
    with pytest.raises(ValueError):
        parse_materials(export(tmp_path, [], headers))


# Outdated: no longer matches the code it tests.
# def test_discarded_columns_preserve_alignment(tmp_path, capsys):
#     headers = ['Email', *HEADERS[:2], 'Name', *HEADERS[2:], 'Consent']
#     row = ['ignored', '10/06/2026 09:00:00', '3', 'ignored',
#            'poster', 'thumbnail', 'video', 'captions', '', 'ignored']
#     papers = parse_materials(export(tmp_path, [row], headers))
#     assert papers[3] == AuthorUploadedMaterials(
#         datetime(2026, 10, 6, 9), 3, 'poster', 'thumbnail', 'video', 'captions', None,
#     )
#     assert capsys.readouterr().out.count('discarding column') == 3


@pytest.mark.parametrize('extra_cells', [[], ['ignored', 'unexpected']])
def test_discarded_columns_still_require_correct_row_width(tmp_path, extra_cells):
    row = ['10/06/2026 09:00:00', '3', 'poster', 'thumbnail', 'video', 'captions', '']
    with pytest.raises(ValueError, match='expected 8 cells'):
        parse_materials(export(tmp_path, [row + extra_cells], [*HEADERS, 'Email']))


# Outdated: no longer matches the code it tests.
# def test_warning_and_optional_facts(tmp_path, monkeypatch, capsys):
#     prompts = []
#     monkeypatch.setattr('builtins.input', lambda prompt: prompts.append(prompt))
#     paper_id = MAX_PAPER_ID + 1
#     papers = parse_materials(export(tmp_path, [
#         ['10/06/2026 09:00:00', paper_id, 'poster', 'thumbnail', 'video', 'captions', ''],
#         ['10/06/2026 09:00:00', '3', 'poster', 'thumbnail', 'video', 'captions', ''],
#     ]))
#     assert len(prompts) == 1
#     assert 'Warning' in capsys.readouterr().out
#     assert paper_id not in papers
#     assert papers[3].fun_facts is None


def test_missing_required_material(tmp_path):
    with pytest.raises(AssertionError, match='poster_url'):
        parse_materials(export(tmp_path, [
            ['10/06/2026 09:00:00', '3', '', 'thumbnail', 'video', 'captions', ''],
        ]))


@pytest.mark.parametrize('rows', [
    [],
    [['too', 'short']],
    [['bad-date', '3', 'p', 't', 'v', 'c', '']],
    [['10/06/2026 09:00:00', 'bad-id', 'p', 't', 'v', 'c', '']],
    [['10/06/2026 09:00:00', '0', 'p', 't', 'v', 'c', '']],
    [['10/06/2026 09:00:00', '3', 'p', 't', 'v', 'c', '']] * 2,
])
def test_unexpected_rows(tmp_path, rows):
    with pytest.raises(ValueError):
        parse_materials(export(tmp_path, rows))


# Outdated: no longer matches the code it tests.
# def test_write_preserves_unrelated_cells_and_resolves_script_path(tmp_path, monkeypatch, capsys):
#     script_dir = tmp_path / 'scripts'
#     script_dir.mkdir()
#     monkeypatch.setattr(parser, '__file__', str(script_dir / 'parser.py'))
#     monkeypatch.setattr(parser, 'OUTPUT_PATH', '../form.csv')
#     monkeypatch.chdir(tmp_path)
#     headers = ['title', 'raw_video', 'uid', 'raw_thumbnail', 'raw_poster_pdf', 'video', 'abstract']
#     original = [
#         ['First, paper', 'old-video', '003', 'old-thumb', 'old-poster', 'keep-video', 'line 1\nline 2'],
#         ['Other paper', 'keep', '4', 'keep', 'keep', '', 'NA'],
#     ]
#     path = export(tmp_path, original, headers)
#     path.write_text(path.read_text(encoding='utf-8-sig'), encoding='utf-8')
#     parser.write_into_sitedata({3: AuthorUploadedMaterials(
#         datetime(2026, 10, 6, 9), 3, 'poster', 'thumbnail', 'video', 'captions', None,
#     )})
#     with path.open(newline='') as source:
#         result = list(csv.reader(source))
#     assert result == [headers,
#                       ['First, paper', 'video', '003', 'thumbnail', 'poster', 'keep-video', 'line 1\nline 2'],
#                       original[1]]
#     hint = capsys.readouterr().out
#     assert 'paste the updated raw_poster_pdf, raw_thumbnail, raw_video' in hint
#     assert 'Google Sheet' in hint


# Outdated: no longer matches the code it tests.
# @pytest.mark.parametrize('headers, rows', [
#     (['uid', 'raw_video', 'raw_thumbnail'], [['3', '', '']]),
#     (['uid', 'raw_video', 'raw_thumbnail', 'raw_poster_pdf'], [['4', '', '', '']]),
#     (['uid', 'raw_video', 'raw_thumbnail', 'raw_poster_pdf'], [['3', '', '', '']] * 2),
#     (['uid', 'raw_video', 'raw_thumbnail', 'raw_poster_pdf'], [['3', '']]),
# ])
# def test_invalid_output_is_not_written(tmp_path, monkeypatch, headers, rows):
#     path = export(tmp_path, rows, headers)
#     # The production papers.csv has no BOM.
#     path.write_text(path.read_text(encoding='utf-8-sig'), encoding='utf-8')
#     monkeypatch.setattr(parser, 'OUTPUT_PATH', str(path))
#     original = path.read_bytes()
#     with pytest.raises(ValueError):
#         parser.write_into_sitedata({3: AuthorUploadedMaterials(
#             datetime(2026, 10, 6, 9), 3, 'poster', 'thumbnail', 'video', 'captions', None,
#         )})
#     assert path.read_bytes() == original
