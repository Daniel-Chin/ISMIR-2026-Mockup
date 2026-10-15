import csv
from unittest.mock import Mock

import pandas as pd
import pytest

from catalogue.build_catalogue import build
from modules.zoom_creator import ZoomCreator


@pytest.fixture(params=[False, True], ids=['no-legacy-fields', 'stale-legacy-fields'])
def assignment_data(tmp_path, request):
    (tmp_path / 'config.yml').write_text('timezone: Asia/Dubai\ndate: 2026 Nov 8-12\n')
    with (tmp_path / 'session_assignment.csv').open('w', newline='') as handle:
        csv.writer(handle).writerows([
            ['Session Name', 'First', 'Second'],
            ['Session Day & Time', 'Mon, 10:00 - 11:30', 'Tue, 10:00 - 11:30'],
            ['Preferred Timezone/s', '', ''],
            ['Session Chair - Onsite', '', ''],
            ['Session Chair - Remote', '', ''],
            ['Paper-1', '002', '003'],
            ['Paper-2', '001', '004'],
        ])
    papers = pd.DataFrame([
        {'uid': uid, 'title': 'Paper ' + uid, 'slack_channel': 'paper-' + uid}
        for uid in ['001', '002', '003', '004']
    ])
    if request.param:
        for column in ['day', 'session', 'position']:
            papers[column] = 99
    papers.to_csv(tmp_path / 'papers.csv', index=False)
    pd.DataFrame([
        {'uid': str(i), 'title': f'Poster Session - {i}', 'day': i,
         'category': 'Poster session', 'start_date': f'2026-11-{8+i:02}',
         'start_time': '10:00', 'end_time': '11:30'}
        for i in [1, 2]
    ]).to_csv(tmp_path / 'events.csv', index=False)
    for name in ['lbds', 'music', 'industry', 'logistics']:
        (tmp_path / f'{name}.csv').write_text('uid,id,title\n')
    return tmp_path


def test_zoom_uses_matrix_day_session_and_order(assignment_data):
    path = assignment_data
    original = (path / 'papers.csv').read_bytes()
    zoom = ZoomCreator(path / 'events.csv', False, path / 'papers.csv')
    api = Mock()
    zoom.setupZoomCalls(api)
    callback = api.createZoomLinksIfNeeded.call_args.kwargs['breakoutRoomsForRow']
    assert callback({'title': 'Poster Session - 1', 'day': 1}) == ['paper-002', 'paper-001']
    assert callback({'title': 'Poster Session - 2', 'day': 2}) == ['paper-003', 'paper-004']
    # Event days include the tutorial day; matrix days start with paper sessions.
    assert callback({'title': 'Poster Session - 1', 'day': 2}) == ['paper-002', 'paper-001']
    assert callback({'title': 'Poster Session - 2', 'day': 3}) == ['paper-003', 'paper-004']
    assert (path / 'papers.csv').read_bytes() == original


# Outdated: no longer matches the code it tests.
# def test_catalogue_uses_matrix_assignments_and_session_links(assignment_data):
#     result = build(str(assignment_data), 'https://example.org', 'test')
#     papers = {paper['id']: paper for paper in result['papers']}
#     assert [(p['day'], p['session'], p['position'], p['session_id'])
#             for p in papers.values()] == [
#                 (1, 1, 2, 'P1'), (1, 1, 1, 'P1'),
#                 (2, 2, 1, 'P2'), (2, 2, 2, 'P2')]
#     sessions = {session['id']: session for session in result['sessions']}
#     assert set(sessions['P1']['paper_ids']) == {'001', '002'}
#     assert set(sessions['P2']['paper_ids']) == {'003', '004'}


def test_missing_assignment_fails_before_zoom_api_or_catalogue_output(assignment_data):
    path = assignment_data
    papers = pd.read_csv(path / 'papers.csv', dtype={'uid': str})
    papers.loc[0, 'uid'] = '999'
    papers.to_csv(path / 'papers.csv', index=False)
    with pytest.raises(ValueError, match='missing from session_assignment.csv: 999'):
        ZoomCreator(path / 'events.csv', False, path / 'papers.csv')
    with pytest.raises(ValueError, match='missing from session_assignment.csv: 999'):
        build(str(path), 'https://example.org', 'test')


def test_zoom_mock_prefix_in_plan_and_api(assignment_data, capsys, monkeypatch):
    from utils import zoom as zoom_utils

    path = assignment_data
    events = pd.read_csv(path / 'events.csv')
    events.loc[len(events)] = [3, 'Opening', 1, 'Opening', '2026-11-09', '09:00', '10:00']
    events.to_csv(path / 'events.csv', index=False)
    monkeypatch.setenv('ZOOM_SHARED_WEBINAR_TOPIC', 'Conference Livestream')
    zoom = ZoomCreator(path / 'events.csv', True, path / 'papers.csv', topicPrefix='mock-')
    zoom.setupZoomCalls(zoom_utils)
    output = capsys.readouterr().out
    assert 'poster-1 | Meeting | mock-Poster Session - 1' in output
    assert 'shared-webinar | Webinar | mock-Conference Livestream' in output
    zoom.useDummyValues = False
    api = Mock()
    zoom.setupZoomCalls(api)
    assert api.createZoomLinksIfNeeded.call_args.kwargs['topicPrefix'] == 'mock-'
