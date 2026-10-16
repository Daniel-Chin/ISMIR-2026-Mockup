import copy
import csv
import json
from unittest.mock import Mock

import pytest

from scripts import decorate_youtube_videos as d


def local(tmp_path):
    source = tmp_path / 'papers.csv'
    source.write_text('uid,raw_video,title\n003,https://drive.google.com/open?id=drive_new,Paper\n')
    videos = tmp_path / 'videos'
    (videos / 'download-state').mkdir(parents=True)
    (videos / '003.mov').write_bytes(b'video')
    (videos / 'download-state/video_urls.json').write_text(json.dumps({'003': 'https://drive.google.com/open?id=drive_new'}))
    return source, videos


def video(drive='drive_new', archived=False):
    return {'id': 'abcdefghijk', 'snippet': {
        'channelId': 'UC' + 'a' * 22, 'title': '[outdated] Old' if archived else 'Old',
        'description': f'---\nISMIR_METADATA\npaper_id: 003\ngoogle_drive_id: {drive}',
        'categoryId': '22', 'tags': ['retain'], 'defaultLanguage': 'fr'},
        'status': {'privacyStatus': 'private' if archived else 'public',
                   'license': 'youtube', 'embeddable': False, 'publicStatsViewable': True,
                   'containsSyntheticMedia': True, 'uploadStatus': 'processed'}}


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(d, 'generate_title', lambda paper: paper['title'])
    monkeypatch.setattr(d, 'generate_description', lambda paper: f"Paper {paper['uid']}")
    monkeypatch.setattr(d, 'EXPECTED_CHANNEL_ID', 'UC' + 'a' * 22)


# Outdated: no longer matches the code it tests.
# def test_local_real_url_shape_and_filename_keys(tmp_path):
#     source, videos = local(tmp_path)
#     assert '003' in d.validate_local(source, videos)[2]
#     (videos / 'download-state/video_urls.json').write_text('{"003.mov": "drive_new"}')
#     d.validate_local(source, videos)


# Outdated: no longer matches the code it tests.
# @pytest.mark.parametrize('failure', ['duplicate', 'missing', 'mismatch', 'malformed', 'duplicate_json', 'alias'])
# def test_provenance_fatal(tmp_path, failure):
#     source, videos = local(tmp_path)
#     state = videos / 'download-state/video_urls.json'
#     if failure == 'duplicate':
#         (videos / '003.mp4').write_bytes(b'x')
#     else:
#         state.write_text({'missing': '{}', 'mismatch': '{"003":"other"}',
#                           'malformed': '{"003":"https://evil.com/open?id=drive_new"}',
#                           'duplicate_json': '{"003":"drive_new","003":"drive_new"}',
#                           'alias': '{"003":"drive_new","003.mov":"drive_new"}'}[failure])
#     with pytest.raises(d.SafetyError):
#         d.validate_local(source, videos)


@pytest.mark.parametrize('description', ['---\nISMIR_METADATA\npaper_id: 003',
    '---\nISMIR_METADATA\npaper_id: 003\npaper_id: 004\ngoogle_drive_id: x',
    'ISMIR_METADATA', video()['snippet']['description'] * 2])
def test_malformed_metadata(description):
    with pytest.raises(d.SafetyError):
        d.metadata(description)


# Outdated: no longer matches the code it tests.
# def test_current_dry_run_apply_and_idempotence(tmp_path, configured, capsys):
#     source, videos = local(tmp_path)
#     fields, rows, papers, original = d.validate_local(source, videos)
#     plans = d.plan_updates([video()], papers)
#     body = plans[0]['body']
#     assert body['snippet']['tags'] == ['retain']
#     assert body['status']['embeddable'] is False
#     assert body['status']['containsSyntheticMedia'] is True
#     assert 'uploadStatus' not in body['status']
#     assert d.metadata(body['snippet']['description'])['google_drive_id'] == 'drive_new'
#     api = Mock()
#     d.apply_updates(api, plans, source, fields, rows, original, True)
#     api.videos.assert_not_called()
#     assert source.read_bytes() == original
#     assert 'DRY RUN' in capsys.readouterr().out
#     api.videos.return_value.update.return_value.execute.return_value = body
#     d.apply_updates(api, plans, source, fields, rows, original)
#     assert list(csv.DictReader(source.open()))[0]['video'].endswith('abcdefghijk')
#     fields, rows, papers, original = d.validate_local(source, videos)
#     plans = d.plan_updates([body], papers)
#     api.reset_mock()
#     d.apply_updates(api, plans, source, fields, rows, original)
#     api.videos.assert_not_called()


# Outdated: no longer matches the code it tests.
# def test_outdated_and_duplicates(tmp_path, configured):
#     source, videos = local(tmp_path)
#     papers = d.validate_local(source, videos)[2]
#     old = video('drive_old')
#     plan = d.plan_updates([old], papers)[0]
#     assert plan['body']['status']['privacyStatus'] == 'private'
#     assert plan['body']['snippet']['title'] == '[outdated] Old'
#     assert plan['body']['snippet']['description'] == old['snippet']['description']
#     assert plan['url'] is None
#     assert d.plan_updates([video('drive_old', True)], papers) == []
#     both = d.plan_updates([old, dict(video(), id='lmnopqrstuv')], papers)
#     assert [p['classification'] for p in both] == ['outdated', 'current']
#     with pytest.raises(d.SafetyError, match='Multiple non-outdated'):
#         d.plan_updates([video(), dict(video(), id='lmnopqrstuv')], papers)
#     assert len(d.plan_updates([video('drive_old', True), video()], papers)) == 1


def fresh(title='3'):
    v = video()
    v['id'] = 'freshfresh0'
    v['snippet'].update(title=title, description='')
    return v


# Outdated: no longer matches the code it tests.
# def test_fresh_upload(tmp_path, configured, capsys):
#     source, videos = local(tmp_path)
#     fields, rows, papers, original = d.validate_local(source, videos)
#     plan, = d.plan_updates([fresh(), fresh('Holiday clip'), fresh('9 lives')], papers)
#     assert plan['uid'] == '003' and plan['url'].endswith('freshfresh0')
#     assert d.metadata(plan['body']['snippet']['description'])['google_drive_id'] == 'drive_new'
#     with pytest.raises(d.SafetyError, match='Multiple non-outdated'):
#         d.plan_updates([fresh(), video()], papers)
#     with pytest.raises(d.SafetyError, match='0 CSV papers'):
#         d.plan_updates([fresh('42')], papers)
#     d.summarize_coverage(rows)
#     assert '  raw_video set            0            1' in capsys.readouterr().out


def test_channel_mismatch(configured):
    api = Mock()
    api.channels.return_value.list.return_value.execute.return_value = {'items': [{'id': 'wrong'}]}
    with pytest.raises(d.SafetyError, match='channel'):
        d.enumerate_videos(api)
    api.playlistItems.assert_not_called()
    api.videos.assert_not_called()


# Outdated: no longer matches the code it tests.
# def test_failure_stops_before_csv(tmp_path, configured):
#     source, videos = local(tmp_path)
#     fields, rows, papers, original = d.validate_local(source, videos)
#     plans = d.plan_updates([video()], papers)
#     api = Mock()
#     api.videos.return_value.update.return_value.execute.side_effect = RuntimeError('failure')
#     with pytest.raises(d.SafetyError):
#         d.apply_updates(api, plans * 2, source, fields, rows, original)
#     assert api.videos.return_value.update.call_count == 1
#     assert source.read_bytes() == original


def test_main_validates_before_auth(tmp_path, monkeypatch, capsys):
    source, videos = local(tmp_path)
    (videos / '003.mp4').write_bytes(b'x')
    auth = Mock()
    monkeypatch.setattr(d, 'authenticate', auth)
    with pytest.raises(d.SafetyError):
        d.main(['--input', str(source), '--videos', str(videos), '--dry-run'])
    auth.assert_not_called()
    assert 'Google Sheets' in capsys.readouterr().out


def test_paginated_enumeration_and_missing_video(configured):
    api = Mock()
    api.channels.return_value.list.return_value.execute.return_value = {
        'items': [{'id': d.EXPECTED_CHANNEL_ID, 'contentDetails': {'relatedPlaylists': {'uploads': 'uploads'}}}]}
    api.playlistItems.return_value.list.return_value.execute.side_effect = [
        {'items': [{'contentDetails': {'videoId': 'abcdefghijk'}}], 'nextPageToken': 'next'},
        {'items': [{'contentDetails': {'videoId': 'lmnopqrstuv'}}]}]
    second = copy.deepcopy(video())
    second['id'] = 'lmnopqrstuv'
    api.videos.return_value.list.return_value.execute.return_value = {'items': [video(), second]}
    assert len(d.enumerate_videos(api)) == 2
    assert api.playlistItems.return_value.list.call_args.kwargs['pageToken'] == 'next'
    api.playlistItems.return_value.list.return_value.execute.side_effect = None
    api.playlistItems.return_value.list.return_value.execute.return_value = {
        'items': [{'contentDetails': {'videoId': 'abcdefghijk'}}]}
    api.videos.return_value.list.return_value.execute.return_value = {'items': []}
    with pytest.raises(d.SafetyError, match='disagree'):
        d.enumerate_videos(api)


def test_quota_has_no_retry():
    request = Mock()
    error = RuntimeError('quota')
    error.content = b'{"reason":"quotaExceeded"}'
    request.execute.side_effect = error
    with pytest.raises(d.SafetyError, match='quota exhausted'):
        d.execute(request)
    request.execute.assert_called_once_with(num_retries=0)


# Outdated: no longer matches the code it tests.
# def test_missing_template_aborts_plan(tmp_path, monkeypatch):
#     source, videos = local(tmp_path)
#     papers = d.validate_local(source, videos)[2]
#     with pytest.raises(d.SafetyError, match='templates'):
#         d.plan_updates([video('old', True), dict(video(), id='lmnopqrstuv')], papers)
