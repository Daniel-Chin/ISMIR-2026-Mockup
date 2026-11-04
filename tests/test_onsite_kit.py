"""The onsite kit's local server (onsit-kit/serve.py)."""

import http.client
import json
import sys
import threading
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'onsit-kit'))
import make_env  # noqa: E402
import materials  # noqa: E402
import serve  # noqa: E402


@pytest.fixture
def server(tmp_path, monkeypatch):
    env = tmp_path / '.onsite_env'
    env.write_text('\n'.join([
        '# a comment',
        'LINK_A=Group | Name | https://example.com/?a=1 | About | more',
        'ONSITE_LBD_START=2026-11-12T15:00:00+04:00',
        'ONSITE_LBD_END=2026-11-12T17:00:00+04:00',
        'ONSITE_LBDS=' + json.dumps([{'uid': uid, 'title': uid, 'authors': '', 'mode': ''} for uid in ('569', 'm1')]),
    ]), encoding='utf-8')
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
    assert info['links'] == [{'group': 'Group', 'name': 'Name', 'url': 'https://example.com/?a=1', 'description': 'About | more'}]


def test_sheet_wins_over_the_local_mirex_list():
    sheet = [{'uid': '569'}, {'uid': 'm1', 'title': 'sheet'}]
    mirex = [{'uid': 'm1', 'title': 'local'}, {'uid': 'm2', 'title': 'local'}]
    assert make_env.merge_mirex(sheet, mirex) == sheet + [mirex[1]]


def test_authors_keep_every_affiliation():
    text = 'Ann Lee (Zayed University; NYU Abu Dhabi)*; Bo Li (KTH); Future MIREX Team'
    assert make_env.people(text) == [['Ann Lee', ['Zayed University', 'NYU Abu Dhabi']], ['Bo Li', ['KTH']],
                                      ['Future MIREX Team', []]]


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
                             'thumbnail': 'none', 'captions': 'missing'}
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


def test_one_materials_job_at_a_time(store):
    store.job = {'running': True}
    assert not store.check()
