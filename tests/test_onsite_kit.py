"""The onsite kit's local server (onsite-kit/serve.py)."""

import http.client
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'onsite-kit'))
import lbdplan  # noqa: E402
import livedb  # noqa: E402
import materials  # noqa: E402
import serve  # noqa: E402


@pytest.fixture
def server(tmp_path, monkeypatch):
    env = tmp_path / '.onsite_env'
    env.write_text('# a comment\nLINK_A=Group | Name | https://example.com/?a=1 | About | more\n', encoding='utf-8')
    reading(tmp_path, [{'uid': uid, 'title': uid, 'authors': '', 'mode': ''} for uid in ('569', 'm1')])
    (tmp_path / 'videos').mkdir()
    (tmp_path / 'videos' / '569.mp4').write_bytes(bytes(range(100)))
    monkeypatch.setattr(serve, 'ENV_FILE', env)
    monkeypatch.setattr(serve, 'MEDIA', tmp_path)
    monkeypatch.setattr(serve, 'STATE', tmp_path / '.state')
    monkeypatch.setattr(serve, 'PROBES', tmp_path / '.state' / 'probes.json')
    monkeypatch.setattr(serve.load_env, '__defaults__', (env,))
    serve.Handler.kit = serve.Kit()
    httpd = ThreadingHTTPServer(('127.0.0.1', 0), serve.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield httpd.server_port
    httpd.shutdown()


def reading(tmp_path, lbds, **more):
    """A last reading of the Live Database, as serve.py keeps it."""
    (tmp_path / '.state').mkdir(exist_ok=True)
    live = {**livedb.EMPTY, 'read_ms': 1, 'timezone': 'Asia/Dubai', 'lbd_start': '2026-11-12T15:00:00+04:00',
            'lbd_end': '2026-11-12T17:00:00+04:00', 'lbds': lbds, **more}
    (tmp_path / '.state' / 'live.json').write_text(json.dumps(live), encoding='utf-8')


def request(port, method, path, body=None, headers=None):
    connection = http.client.HTTPConnection('127.0.0.1', port)
    connection.request(method, path, json.dumps(body) if body is not None else None, headers or {})
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response, data


def test_env_rows_keep_extra_pipes_in_the_last_column(server):
    _, data = request(server, 'GET', '/api/info')
    info = json.loads(data)
    assert info['links'][-1] == {'group': 'Group', 'name': 'Name', 'url': 'https://example.com/?a=1', 'description': 'About | more'}
    assert info['links'][0]['name'] == 'Miniconf' and info['links'][0]['url'].startswith('https://')  # from config.yml


def test_poster_screens_split_every_poster_in_group_order(server, tmp_path):
    lbds = [{'uid': uid, 'title': uid, 'group': group, 'mode': 'Virtual'} for uid, group in
            [('m2', '7'), ('m1', '7'), ('600', '2'), ('569', '1'), ('601', '2'), ('570', '1')]]
    lbds += [{'uid': '602', 'group': '2', 'mode': 'In-Person'}, {'uid': '603', 'group': '2', 'mode': 'Virtual', 'ok': 'No'}]
    reading(tmp_path, lbds)
    serve.Handler.kit = serve.Kit()
    serve.Handler.kit.plan.pop('posters', None)  # worked out here, not the plan's
    screens = [json.loads(request(server, 'GET', f'/api/lbd/P{n}')[1]) for n in range(1, 5)]
    # No m1, nor the LBDs presented in person or not cleared to present; each run reordered clear of the videos.
    assert [sorted(screen['plays']) for screen in screens] == [['569', '570'], ['600', '601'], ['m2'], []]
    assert {screen['poster_s'] for screen in screens} == {3600}  # two posters a screen at most, 7200 s
    assert request(server, 'GET', '/api/lbd/P5')[0].status == 404
    serve.Handler.kit.plan['posters'] = {'P2': {'plays': ['601', '600'], 'poster_s': 90}}  # as the LBD plan fixes it
    fixed = json.loads(request(server, 'GET', '/api/lbd/P2')[1])
    assert (fixed['plays'], fixed['poster_s']) == (['601', '600'], 90)
    change = {'rev': 0, 'plays': ['569'], 'poster_s': 60, 'timetable_s': 0, 'start_ms': 1}
    assert request(server, 'POST', '/api/lbd/P1', change)[0].status == 200
    assert json.loads(request(server, 'GET', '/api/posters')[1])[0]['posters'] == 1


def test_posters_keep_clear_of_their_own_videos(server):
    blocked = {('a', 0), ('a', 1), ('b', 1)}
    order = serve.arrange(['a', 'b', 'c'], lambda uid, spot: (uid, spot) not in blocked)
    assert all((uid, spot) not in blocked for spot, uid in enumerate(order)) and sorted(order) == ['a', 'b', 'c']
    video = json.loads(request(server, 'GET', '/api/lbd/6')[1])
    change = {'rev': 0, 'plays': ['569'], 'poster_s': 60, 'timetable_s': 0, 'start_ms': video['start_ms']}
    assert request(server, 'POST', '/api/lbd/P1', change)[0].status == 200
    found = json.loads(request(server, 'GET', '/api/conflicts')[1])['conflicts']
    assert [(c['uid'], c['poster_screen'], c['video_screen']) for c in found] == [('569', 'P1', '6')]


def test_authors_keep_every_affiliation():
    text = 'Ann Lee (Zayed University; NYU Abu Dhabi)*; Bo Li (University of Illinois (UIUC)); Future MIREX Team'
    assert livedb.people(text) == [['Ann Lee', ['Zayed University', 'NYU Abu Dhabi']],
                                    ['Bo Li', ['University of Illinois (UIUC)']], ['Future MIREX Team', []]]
    row = {'uid': '1', 'title': 'T', 'authors_and_affil_from_pdf': text, 'presentation_mode': 'Virtual',
           'raw_video_path': 'https://drive.google.com/open?id=' + 'v' * 25}
    lbd = livedb.lbd_rows([row])[0]
    assert lbd['authors'] == 'Ann Lee; Bo Li; Future MIREX Team' and lbd['file_ids'] == ['v' * 25]


def test_refuses_other_hosts(server):
    response, _ = request(server, 'GET', '/api/info', headers={'Host': 'evil.example:8765'})
    assert response.status == 403


def test_video_byte_ranges(server):
    response, data = request(server, 'GET', '/media/videos/569.mp4', headers={'Range': 'bytes=10-19'})
    assert response.status == 206
    assert response.getheader('Content-Range') == 'bytes 10-19/100'
    assert data == bytes(range(10, 20))


def test_cannot_read_outside_the_served_folders(server):
    response, _ = request(server, 'GET', '/media/../.onsite_env')
    assert response.status == 404


def test_schedule_saves_and_rejects_stale_tabs(server):
    _, data = request(server, 'GET', '/api/lbd/7')
    plan = json.loads(data)
    assert plan['rev'] == 0 and plan['slot_s'] == 7200 and plan['utc_offset'] == '+04:00'
    change = {'rev': 0, 'plays': ['m1'], 'poster_s': 0, 'timetable_s': 5, 'start_ms': 1}
    response, _ = request(server, 'POST', '/api/lbd/7', change)
    assert response.status == 200
    response, _ = request(server, 'POST', '/api/lbd/7', change)
    assert response.status == 409
    response, _ = request(server, 'POST', '/api/lbd/7', {**change, 'rev': 1, 'plays': ['nope']})
    assert response.status == 400
    request(server, 'POST', '/api/lbd/7', {'rev': 1, 'reset': True})
    _, data = request(server, 'GET', '/api/lbd/7')
    assert json.loads(data)['plays'] == serve.Handler.kit.plan['screens']['7']['plays']


def test_measured_length_replaces_the_default(server):
    request(server, 'POST', '/api/measured', {'569': {'size': 100, 'seconds': 12.5}})
    _, data = request(server, 'GET', '/api/lbd/6')
    assert json.loads(data)['seconds']['569'] == 12.5
    request(server, 'POST', '/api/measured', {'569': {'size': 100, 'seconds': None}})
    _, data = request(server, 'GET', '/api/lbd/6')
    assert json.loads(data)['problems'] == {'569': 'unplayable'}


def test_folder_page_and_file_names():
    page = ('<div class="flip-entry" id="entry-abc"><a href="https://drive.google.com/drive/folders/abc"><div>x</div>'
            '<div class="flip-entry-title">A&amp;B</div></a></div>'
            '<div class="flip-entry" id="entry-def"><a href="https://drive.google.com/file/d/def/view">'
            '<div class="flip-entry-title">569_poster.pdf</div></a></div>')
    assert [(e[0], e[2]) for e in materials.ENTRY.findall(page)] == [('abc', 'A&amp;B'), ('def', '569_poster.pdf')]
    names = {'569_lbd.pdf': 'paper', '569_poster.pdf': 'poster', '569_thumbnail.png': 'thumbnail',
             '569_video.mp4': 'video', '569_video.srt': 'captions', '569_captions.zip': 'captions',
             'captions.sbv.zip': 'captions', 'AudioKey_K10_video.mp4': 'video'}
    assert {name: materials.kind_of(name) for name in names} == names


@pytest.fixture
def store(tmp_path, monkeypatch):
    def fake_transfer(self, remote, part):
        if remote['id'] == 'blocked':
            raise RuntimeError('quota')
        part.write_bytes(b'x' * remote['size'])

    monkeypatch.setattr(materials.Materials, 'transfer', fake_transfer)
    lbds = [{'uid': 'm1', 'title': 'T', 'folder': 'Task_X'}]
    result = materials.Materials(tmp_path, tmp_path / '.state', ['root'], lbds, {'7': {'plays': ['m1']}})
    result.listing['files'] = {'m1': {
        'video': {'id': 'v', 'name': 'Task_X_video.mp4', 'size': 10},
        'poster': {'id': 'p', 'name': 'Task_X_poster.pdf', 'size': 5},
        'paper': {'id': 'blocked', 'name': 'Task_X_lbd.pdf', 'size': 7},
        'captions': {'id': 'c', 'name': 'x.zip', 'size': None},
    }}
    return result


def states(store):
    return {kind: file['state'] for kind, file in store.snapshot()['rows'][0]['files'].items()}


def wait(store):
    while store.job.get('running'):
        pass


def test_materials_status_download_and_update(store, tmp_path):
    assert states(store) == {'paper': 'missing', 'poster': 'missing', 'video': 'missing',
                             'thumbnail': 'none', 'captions': 'missing', 'channel': 'none', 'subtitles': 'none'}
    assert store.download(['m1/video', 'm1/paper', 'm1/captions'])
    wait(store)
    assert store.job['files'] == 2 and store.job['files_done'] == 1  # captions have no known size
    assert 'quota' in store.job['failed'][0]
    assert (tmp_path / 'videos' / 'm1.mp4').stat().st_size == 10
    assert states(store)['video'] == 'current'
    (tmp_path / 'videos' / 'm1.mp4').write_bytes(b'old')
    assert states(store)['video'] == 'changed'
    store.listing['files']['m1']['video'].update(name='Task_X_video.webm')
    assert store.download(['m1/video'])
    wait(store)
    assert [file.name for file in (tmp_path / 'videos').iterdir()] == ['m1.webm']


def test_channel_codes_lie_loose_in_their_folder(tmp_path, monkeypatch):
    listings = {'root': [{'id': 'f', 'name': '569', 'folder': True},
                         {'id': 'a', 'name': 'LBD_569_lbd569-groovyui.png', 'folder': False},
                         {'id': 'b', 'name': 'LBD_group6_lbd-g6-human.png', 'folder': False},
                         {'id': 'm', 'name': 'LBD_m7_lbd-m7-a-transcription.png', 'folder': False},
                         {'id': 'c', 'name': 'LBD_999_unknown.png', 'folder': False},
                         {'id': 's', 'name': '569.vtt', 'folder': False},
                         {'id': 't', 'name': 'm7.vtt', 'folder': False},
                         {'id': 'u', 'name': '999.vtt', 'folder': False}],
                'f': [{'id': 'v', 'name': '569_video.mp4', 'folder': False}]}
    monkeypatch.setattr(materials, 'list_folder', listings.get)
    monkeypatch.setattr(materials, 'drive_size', lambda file_id: 1)
    lbds = [{'uid': '569', 'title': 'T'}, {'uid': 'm7', 'title': 'M'}, {'uid': 'g6', 'title': 'Group 6'}]
    store = materials.Materials(tmp_path, tmp_path / '.state', ['root'], lbds, {})
    store.job = {'done': 0, 'total': 0, 'failed': []}
    store.check_drive()
    files = store.listing['files']
    assert sorted(files['569']) == ['channel', 'subtitles', 'video'] and files['g6']['channel']['id'] == 'b'
    assert files['m7']['channel']['id'] == 'm' and files['m7']['subtitles']['id'] == 't'
    assert '999' not in files


def test_one_materials_job_at_a_time(store):
    store.job = {'running': True}
    assert not store.check()


def test_talk_sessions_join_the_sheets():
    events = [{'title': 'Oral Session - 1', 'category': 'Oral session', 'start_date': '2026-11-09', 'start_time': '10:00',
               'end_time': '10:30', 'onsite_location': 'A6'},
              {'title': '★ Award Nominees\nOral Session - 1', 'category': 'Award nominee', 'start_date': '2026-11-09',
               'start_time': '18:00', 'end_time': '19:00', 'onsite_location': 'A6'}]
    papers = [{'uid': '7', 'title': 'Seven', 'authors_and_affil': 'Ann Lee (KAIST); Bo Li (NYU)', 'raw_pdf_path': 'P7'}]
    drive = 'https://drive.google.com/open?id='
    oral = [{'cmt id': '7', 'title': 'x', 'session_index': '1', 'position_in_session': '2', 'chair_onsite': 'C',
             'chair_remote': 'R', 'presenter': 'Ann', 'modality': 'Remote',
             'slides_pdf': drive + 'a' * 25, 'slides_preferred': drive + 'b' * 25}]
    award = [{'cmt id': '7', 'title': 'x', 'award_session_index': 'A1', 'position_in_session': '1', 'chair_onsite': 'C',
              'chair_remote': 'R', 'presenter': 'Ann', 'modality': 'Remote', 'slides_pdf': ''}]
    zone = livedb.venue_zone('Asia/Dubai')
    sessions, found = livedb.talk_sessions(events, papers, oral, award, zone)
    assert [s['key'] for s in sessions] == ['O1', 'A1'] and sessions[1]['title'] == '★ Award Nominees · Oral Session - 1'
    assert sessions[0]['start'] == '2026-11-09T10:00:00+04:00' and sessions[0]['papers'][0]['position'] == 2
    assert found['7']['authors'] == 'Ann Lee; Bo Li'
    assert found['7']['files'] == {'slides_pdf': drive + 'a' * 25, 'award_slides_pdf': ''}  # slides PDFs only
    assert livedb.mended('JosÃ\xa9') == 'José' and livedb.mended('José') == 'José'


def test_talks_are_read_from_the_sheets_and_files_open(server, tmp_path, monkeypatch):
    kit = serve.Handler.kit
    json_headers = {'Content-Type': 'application/json'}
    response, data = request(server, 'POST', '/api/live', {}, json_headers)
    assert response.status == 502 and b'SHEET_' in data  # no sheets in .onsite_env
    sheets = {
        'oral': [{'cmt id': '7', 'session_index': '1', 'position_in_session': '1',
                  'slides_pdf': 'https://docs.google.com/presentation/d/' + 's' * 25 + '/edit'}],
        'award': [{'cmt id': '7', 'award_session_index': 'A1', 'position_in_session': '1', 'slides_pdf': 'A note, not a link'}],
        'papers': [{'uid': '7', 'title': 'Seven', 'raw_pdf_path': 'https://drive.google.com/open?id=' + 'p' * 25}],
        'events': []}
    kit.sheet_links = {'ORAL_SESSIONS': 'oral', 'AWARD_SESSIONS': 'award', 'PAPERS': 'papers', 'EVENTS': 'events'}
    kit.talk_materials.has_sheets = True
    monkeypatch.setattr(livedb, 'sheet_rows', sheets.__getitem__)
    response, _ = request(server, 'POST', '/api/live', {}, json_headers)
    assert response.status == 200
    assert [s['key'] for s in json.loads(request(server, 'GET', '/api/talks')[1])['sessions']] == ['A1', 'O1']
    assert json.loads((tmp_path / '.state' / 'live.json').read_text(encoding='utf-8'))['talks']['7']['title'] == 'Seven'
    assert serve.Kit().talks['7']['title'] == 'Seven'  # kept for the next start, offline too

    store = kit.talk_materials
    monkeypatch.setattr(materials, 'link_file', lambda url: {'name': 'deck.pptx' if 'presentation' in url else '7.pdf',
                                                             'size': None if 'presentation' in url else 3})
    store.job = {'done': 0, 'total': 0, 'failed': []}
    store.check_drive()
    assert sorted(store.listing['files']['7']) == ['slides_pdf'] and store.job['failed'] == []
    assert store.listing['files']['7']['slides_pdf']['unsized']
    (tmp_path / 'talks' / 'slides_pdf').mkdir(parents=True)
    (tmp_path / 'talks' / 'slides_pdf' / '7.pptx').write_bytes(b'deck')
    assert store.status('7', 'slides_pdf')['state'] == 'unknown' and 'paper' not in store.kinds
    award, oral = (session['papers'][0] for session in kit.sessions()['sessions'])
    assert oral['files'] == {'slides': {'kind': 'slides_pdf', 'name': '7.pptx'}} and award['files'] == {}
    assert award['slides_note'] == 'A note, not a link' and not oral['slides_note']

    opened = []
    monkeypatch.setattr(serve.platform, 'release', lambda: 'plain')  # not WSL, which asks wslpath first
    monkeypatch.setattr(serve.subprocess, 'Popen', lambda command: opened.append(command))
    monkeypatch.setattr(serve.os, 'startfile', lambda file: opened.append(file), raising=False)
    response, _ = request(server, 'POST', '/api/talks/open', {'uid': '7', 'kind': 'slides_pdf', 'reveal': True}, json_headers)
    assert response.status == 200 and opened
    response, _ = request(server, 'POST', '/api/talks/open', {'uid': '7', 'kind': 'award_slides_pdf'}, json_headers)
    assert response.status == 404  # not downloaded
    response, _ = request(server, 'POST', '/api/talks/open', {'uid': '7', 'kind': 'slides_pdf'},
                          {**json_headers, 'Origin': 'https://elsewhere.example'})
    assert response.status == 403
    response, _ = request(server, 'POST', '/api/talks/open', {'uid': '7', 'kind': 'slides_pdf'}, {'Content-Type': 'text/plain'})
    assert response.status == 403


def test_mirex_folders_are_found_by_their_files(tmp_path, monkeypatch):
    listings = {'root': [{'id': 'f', 'name': '569', 'folder': True}, {'id': 't', 'name': 'Task_X', 'folder': True},
                         {'id': 'o', 'name': 'Other', 'folder': True}],
                'f': [{'id': 'v1', 'name': '569_video.mp4', 'folder': False}],
                't': [{'id': 'v2', 'name': 'Task_X_video.mp4', 'folder': False},
                      {'id': 'p2', 'name': 'Task_X_poster.pdf', 'folder': False}],
                'o': [{'id': 'zz', 'name': 'x.pdf', 'folder': False}]}
    monkeypatch.setattr(materials, 'list_folder', listings.get)
    monkeypatch.setattr(materials, 'drive_size', lambda file_id: 1)
    lbds = [{'uid': '569', 'title': 'L'}, {'uid': 'm1', 'title': 'M', 'file_ids': ['v2']}]
    store = materials.Materials(tmp_path, tmp_path / '.state', ['root'], lbds, {})
    store.job = {'done': 0, 'total': 0, 'failed': []}
    store.check_drive()
    assert sorted(store.listing['files']['m1']) == ['poster', 'video'] and '569' in store.listing['files']
    assert store.listing['unmatched'] == ['Other']


def test_live_database_reading_builds_every_page(monkeypatch):
    tabs = {
        'EVENTS': [{'title': 'LBD Session', 'category': 'LBD', 'start_date': '2026-11-12', 'start_time': '15:00',
                    'end_time': '17:00', 'live_url': 'https://zoom.example/j/1'},
                   {'title': 'Poster Session - 3', 'category': 'Poster session', 'start_date': '2026-11-10',
                    'start_time': '9:00', 'end_time': '10:00', 'onsite_location': 'Hall'}],
        'LBDS': [{'uid': '569', 'title': 'L', 'group_id': '1', 'presentation_mode': 'Virtual', 'new column': 'x'}],
        'LBD_GROUPS': [{'group_id': '1', 'theme': 'Generation', 'slack_channel': 'lbd-g1'}]}
    monkeypatch.setattr(livedb, 'sheet_rows', lambda link: tabs[link])
    live = livedb.read({name: name for name in tabs}, {'timezone': 'Asia/Dubai', 'miniconf_url': 'https://site/'})
    assert (live['lbd_start'], live['lbd_end']) == ('2026-11-12T15:00:00+04:00', '2026-11-12T17:00:00+04:00')
    assert live['shared_zoom'] == 'https://zoom.example/j/1' and live['groups'] == {'1': 'Generation'}
    assert live['poster_sessions'][0]['start'] == '2026-11-10T09:00:00+04:00'
    assert live['poster_sessions'][0]['miniconf'] == 'https://site/papers.html?session=3&type=poster'
    assert live['lbds'][0]['mode'] == 'Virtual' and live['sessions'] == []
    links = livedb.link_rows({'miniconf_url': 'https://site'}, {'SHEET_LBDS': 'https://sheet', 'DRIVE_FOLDER_LBD': 'https://d'}, live)
    assert ('Live Database', 'LBDs', 'https://sheet') in [(r['group'], r['name'], r['url']) for r in links]
    assert ('Materials', 'LBD Drive folder', 'https://d') in [(r['group'], r['name'], r['url']) for r in links]
    assert livedb.site_config(Path(__file__).resolve().parents[1] / 'sitedata' / 'config.yml')['timezone'] == 'Asia/Dubai'


def test_the_plan_follows_the_live_database():
    reference = {'screens': {'1': {'name': 'One', 'plays': ['a1', 'a2', 'a1', 'a2']}, '2': {'name': 'Two', 'plays': []},
                             '7': {'name': 'MIREX', 'plays': []}}, 'video_s': {'a1': 1000}}
    lbd = lambda uid, group, **more: {'uid': uid, 'group': group, 'mode': 'Virtual', **more}
    lbds = [lbd('a1', '1'), lbd('a2', '1'), lbd('a3', '1'), lbd('b1', '2'), lbd('x', '1', mode='In-Person'),
            lbd('y', '2', ok='No'), lbd('m1', '7', mode='In-Person'), lbd('m2', '7')]
    lengths = {'a1': 1000, 'a2': 1000, 'a3': 1700, 'b1': 100, 'm1': 50, 'm2': 50, 'x': 10, 'y': 10}
    plan, problems = lbdplan.build(reference, lbds, {'1': 'Topic one'}, lengths.get, 0, 7200)
    one, two, mirex = (plan['screens'][key] for key in ('1', '2', '7'))
    # a3 is new and the longest: its second play does not fit on screen 1, and goes where there is most time.
    assert one['plays'] == ['a1', 'a2', 'a3', 'a1', 'a2'] and two['plays'] == ['b1', 'b1', 'a3']
    assert mirex['plays'] == ['m1', 'm2'] * 3 and problems == []  # m1 though in person; x and y not at all
    assert one['theme'] == 'Topic one' and one['timetable_s'] == min(20, (7200 - 5700) // 5)
    assert sorted(uid for screen in plan['posters'].values() for uid in screen['plays']) == ['a1', 'a2', 'a3', 'b1', 'm2']
    assert any(line.startswith('Screen 1: adds a3') for line in lbdplan.changes(reference, plan))
    _, problems = lbdplan.build(reference, lbds + [lbd('c1', '9')], {}, lambda uid: lengths.get(uid, 0) or None, 0, 7200)
    assert problems == ['c1: group 9 has no video screen']


def test_mp4_length_from_its_header(tmp_path):
    mvhd = b'\0\0\0\0' + bytes(8) + (1000).to_bytes(4, 'big') + (2500).to_bytes(4, 'big') + bytes(80)
    box = lambda kind, body: (8 + len(body)).to_bytes(4, 'big') + kind + body
    (tmp_path / 'a.mp4').write_bytes(box(b'ftyp', b'isom') + box(b'moov', box(b'mvhd', mvhd)) + box(b'mdat', b'x'))
    assert lbdplan.mp4_seconds(tmp_path / 'a.mp4') == 2.5 and lbdplan.mp4_seconds(tmp_path / 'none.mp4') is None


def test_updating_the_screens_from_the_live_database(server, tmp_path, monkeypatch):
    kit = serve.Handler.kit
    kit.live['lbds'] = [{'uid': '569', 'group': '6', 'mode': 'Virtual'}, {'uid': '600', 'group': '6', 'mode': 'Virtual'}]
    monkeypatch.setattr(kit, 'read_live', lambda: None)
    monkeypatch.setattr(kit, 'video_length', lambda uid: 100)
    request(server, 'POST', '/api/lbd/6', {'rev': 0, 'plays': ['569'], 'poster_s': 0, 'timetable_s': 5, 'start_ms': 7})
    status = json.loads(request(server, 'GET', '/api/lbd-plan')[1])
    assert any(line.startswith('Screen 6: adds 600') for line in status['changes'])
    response, data = request(server, 'POST', '/api/lbd-plan', {}, {'Content-Type': 'application/json'})
    assert response.status == 200 and '6' in json.loads(data)['reset']
    screen = json.loads(request(server, 'GET', '/api/lbd/6')[1])
    assert screen['plays'] == ['569', '600', '569', '600'] and screen['start_ms'] == 7  # the edits gone, the start kept
    assert json.loads((tmp_path / '.state' / 'lbd_plan.json').read_text(encoding='utf-8'))['screens']['1']['plays'] == []
    assert json.loads(request(server, 'GET', '/api/lbd-plan')[1])['changes'] == []
    # Edits in Manage alone count too: the screens show the plan once updated.
    edit = {'rev': screen['rev'], 'plays': ['569'], 'poster_s': 0, 'timetable_s': 5, 'start_ms': 7}
    assert request(server, 'POST', '/api/lbd/6', edit)[0].status == 200
    assert json.loads(request(server, 'GET', '/api/lbd-plan')[1])['changes'] == ['Screen 6: edited in Manage (1 plays), the plan has 4']
    request(server, 'POST', '/api/lbd-plan', {}, {'Content-Type': 'application/json'})
    assert json.loads(request(server, 'GET', '/api/lbd/6')[1])['plays'] == ['569', '600', '569', '600']
