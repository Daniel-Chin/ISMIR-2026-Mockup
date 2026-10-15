# Outdated: scripts/download_and_rename_videos.py no longer exists.
# import csv
# import json
# from pathlib import Path

# import pytest

# from scripts import download_and_rename_videos as downloader


# def setup_run(tmp_path, recorded, existing=True):
#     source = tmp_path / 'papers.csv'
#     with source.open('w', newline='') as stream:
#         writer = csv.writer(stream)
#         writer.writerows([['uid', 'raw_video'], ['003', 'new-url'], ['4', '']])
#     output = tmp_path / 'videos'
#     state = output / 'download-state'
#     state.mkdir(parents=True)
#     (state / 'video_urls.json').write_text(json.dumps(recorded))
#     if existing:
#         (output / '003.mp4').write_bytes(b'x' * 2048)
#     return source, output, state


# @pytest.mark.parametrize('recorded,existing,skip', [
#     ({'003': 'new-url'}, True, True),
#     ({'003': 'old-url'}, True, False),
#     ({}, True, False),
#     ({'003': 'new-url'}, False, False),
# ])
# def test_skip_requires_file_and_matching_url(tmp_path, monkeypatch, recorded, existing, skip):
#     source, output, state = setup_run(tmp_path, recorded, existing)
#     calls = []
#     totals = []
#     original_tqdm = downloader.tqdm

#     def progress(items, **kwargs):
#         bar = original_tqdm(items, **kwargs)
#         totals.append(bar.total)
#         return bar

#     progress.write = original_tqdm.write
#     monkeypatch.setattr(downloader, 'tqdm', progress)

#     def download(**kwargs):
#         calls.append(kwargs['url'])
#         assert '003' not in json.loads((state / 'video_urls.json').read_text())
#         assert not (output / '003.mp4').exists()
#         path = Path(kwargs['output']) / 'author.mov'
#         path.write_bytes(b'y' * 2048)
#         return str(path)

#     monkeypatch.setattr(downloader.gdown, 'download', download)
#     assert downloader.download_videos(source, output) == 0
#     assert calls == ([] if skip else ['new-url'])
#     assert totals == [0 if skip else 1]
#     assert json.loads((state / 'video_urls.json').read_text()) == {'003': 'new-url'}
#     assert (state / 'new_videos.log').read_text() == ('' if skip else '003\n')
#     assert (output / ('003.mp4' if skip else '003.mov')).is_file()


# @pytest.mark.parametrize('result', ['failure', 'tiny'])
# def test_failed_replacement_leaves_no_record(tmp_path, monkeypatch, result):
#     source, output, state = setup_run(tmp_path, {'003': 'old-url', '4': 'retained-url'})

#     def download(**kwargs):
#         if result == 'failure':
#             return None
#         path = Path(kwargs['output']) / 'tiny.mp4'
#         path.write_bytes(b'x')
#         return str(path)

#     monkeypatch.setattr(downloader.gdown, 'download', download)
#     assert downloader.download_videos(source, output) == 1
#     assert json.loads((state / 'video_urls.json').read_text()) == {'4': 'retained-url'}
#     assert not (output / '003.mp4').exists()
#     assert (state / 'new_videos.log').read_text() == ''


# def test_failed_invalidation_preserves_video(tmp_path, monkeypatch):
#     source, output, state = setup_run(tmp_path, {'003': 'old-url'})
#     original_write = downloader.atomic_write

#     def write(path, contents):
#         if path.name == 'video_urls.json' and json.loads(contents) == {}:
#             raise OSError('Cannot save state')
#         original_write(path, contents)

#     monkeypatch.setattr(downloader, 'atomic_write', write)
#     monkeypatch.setattr(downloader.gdown, 'download', lambda **kwargs: pytest.fail('Must not download'))
#     assert downloader.download_videos(source, output) == 1
#     assert (output / '003.mp4').read_bytes() == b'x' * 2048
#     assert json.loads((state / 'video_urls.json').read_text()) == {'003': 'old-url'}


# @pytest.mark.parametrize('outcomes,attempts', [
#     ([False, False, False, True], 3),
#     ([False, False, True, False, False, True], 6),
# ])
# def test_consecutive_failure_limit(tmp_path, monkeypatch, capsys, outcomes, attempts):
#     source, output, state = setup_run(tmp_path, {}, existing=False)
#     uids = [str(index) for index in range(len(outcomes))]
#     recorded = {uid: 'old-url' for uid in uids}
#     (state / 'video_urls.json').write_text(json.dumps(recorded))
#     for uid in uids:
#         (output / f'{uid}.mp4').write_bytes(b'x' * 2048)
#     with source.open('w', newline='') as stream:
#         writer = csv.writer(stream)
#         writer.writerow(['uid', 'raw_video'])
#         writer.writerows((uid, f'new-url-{uid}') for uid in uids)
#     calls = []

#     def download(**kwargs):
#         index = len(calls)
#         calls.append(kwargs['url'])
#         if not outcomes[index]:
#             return None
#         path = Path(kwargs['output']) / 'video.mp4'
#         path.write_bytes(b'y' * 2048)
#         return str(path)

#     monkeypatch.setattr(downloader.gdown, 'download', download)
#     assert downloader.download_videos(source, output) == outcomes[:attempts].count(False)
#     assert len(calls) == attempts
#     successful = [uid for uid in uids[:attempts] if outcomes[int(uid)]]
#     assert (state / 'new_videos.log').read_text().splitlines() == successful
#     saved = json.loads((state / 'video_urls.json').read_text())
#     for uid in uids[attempts:]:
#         assert saved[uid] == 'old-url'
#         assert (output / f'{uid}.mp4').read_bytes() == b'x' * 2048
#     summary = capsys.readouterr().out
#     assert f'Downloaded {len(successful)} videos' in summary
#     assert f'not attempted {len(outcomes) - attempts}' in summary
