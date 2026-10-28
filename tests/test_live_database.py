from unittest.mock import Mock

import pytest

from utils import live_database as db
from utils.live_database import CellChange


def sheet(monkeypatch, grids, answer='y'):
    """A papers tab whose reads return `grids` in turn; the Sheets API mock is returned."""
    monkeypatch.setenv('PAPERS_SHEET_URL', 'https://docs.google.com/spreadsheets/d/SHEET/edit?gid=7#gid=7')
    api = Mock()
    api.get.return_value.execute.return_value = {'sheets': [{'properties': {'sheetId': 7, 'title': 'papers'}}]}
    api.values.return_value.get.return_value.execute.side_effect = [{'values': grid} for grid in grids]
    service = Mock()
    service.spreadsheets.return_value = api
    monkeypatch.setattr('googleapiclient.discovery.build', lambda *args, **kwargs: service)
    monkeypatch.setattr('builtins.input', lambda prompt: answer)
    return api


BEFORE = [['uid', 'title', 'raw_video'], ['3', 'A', 'old'], ['4', 'B']]
CHANGES = [CellChange('3', 'raw_video', 'old', 'new'), CellChange('4', 'raw_video', '', 'first')]


def test_writes_after_confirmation_and_verifies(monkeypatch):
    after = [['uid', 'title', 'raw_video'], ['3', 'A', 'new'], ['4', 'B', 'first']]
    api = sheet(monkeypatch, [BEFORE, after])
    assert db.update_papers_tab(CHANGES, credentials=None)
    body = api.values.return_value.batchUpdate.call_args.kwargs['body']
    assert body['valueInputOption'] == 'RAW'
    assert body['data'] == [{'range': "'papers'!C2", 'values': [['new']]},
                            {'range': "'papers'!C3", 'values': [['first']]}]


def test_declined_writes_nothing(monkeypatch):
    api = sheet(monkeypatch, [BEFORE], answer='n')
    assert not db.update_papers_tab(CHANGES, credentials=None)
    api.values.return_value.batchUpdate.assert_not_called()


def test_sheet_changed_since_pull_writes_nothing(monkeypatch):
    api = sheet(monkeypatch, [[['uid', 'title', 'raw_video'], ['3', 'A', 'edited by hand'], ['4', 'B']]])
    with pytest.raises(SystemExit):
        db.update_papers_tab(CHANGES, credentials=None)
    api.values.return_value.batchUpdate.assert_not_called()


def test_read_back_mismatch_fails(monkeypatch):
    sheet(monkeypatch, [BEFORE, BEFORE])
    with pytest.raises(SystemExit):
        db.update_papers_tab(CHANGES, credentials=None)


def test_column_letter():
    assert [db.column_letter(i) for i in (0, 25, 26, 32)] == ['A', 'Z', 'AA', 'AG']
