"""
Sets the title. description, captions, and other metadata for YouTube videos.  
uv run python -m scripts.decorate_youtube_videos --dry-run
"""

from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import tempfile
import unicodedata
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, NotRequired, TypedDict, cast

import pyperclip
from tqdm import tqdm

from utils.session_assignment import parse_file
from utils.shared import load_site_config

if TYPE_CHECKING:
    from googleapiclient.discovery import Resource
    from googleapiclient.http import HttpRequest
from urllib.parse import parse_qs, urlparse

EXPECTED_CHANNEL_ID = 'UC_L9sCoMJqF3I42IAbO7Bfg'    # change this to your channel ID. https://www.youtube.com/account_advanced
ROOT = Path(__file__).resolve().parent.parent
# Tracks named otherwise are never touched.
CAPTION_NAME_PATTERN = r'official \([0-9A-Za-z]{5}\)'
SCOPES = ['https://www.googleapis.com/auth/youtube.force-ssl']
SNIPPET_FIELDS = {'title', 'description', 'categoryId', 'defaultLanguage', 'tags',
                  'defaultAudioLanguage'}
STATUS_FIELDS = {'privacyStatus', 'license', 'embeddable', 'publicStatsViewable',
                 'publishAt', 'selfDeclaredMadeForKids', 'containsSyntheticMedia'}


# The API's discovery-generated payloads are dynamic.
APIObject = dict[str, Any]


class PaperRow(TypedDict):
    """CSV cells are strings; optional columns may be absent in smaller exports."""

    uid: str
    title: str
    authors_and_affil: str
    abstract: str
    raw_video: str
    raw_captions: str
    video: NotRequired[str]


class Metadata(TypedDict):
    paper_id: str
    google_drive_id: str
    caption_drive_id: NotRequired[str]


class CaptionPlan(TypedDict):
    # None removes our tracks; path is set whenever drive_id is.
    drive_id: str | None
    path: str | None


class UpdatePlan(TypedDict):
    uid: str
    body: APIObject
    before: dict[str, APIObject]
    url: str | None
    classification: Literal['current', 'outdated']
    caption: CaptionPlan | None


def generate_title(paper: PaperRow) -> str:
    _, papers = parse_file('./sitedata/')
    matches = [p for p in papers if p.uid == paper['uid']]
    if len(matches) != 1:
        raise SafetyError(f'Paper {paper["uid"]} appears {len(matches)} times in session_assignment.csv')
    p, = matches
    proposal = f'P{p.session_index}-{p.position} {paper["title"]}'
    return proposal[:100]


def generate_description(paper: PaperRow) -> str:
    config = load_site_config('./sitedata/')
    conf_name = config['name']
    miniconf_url = config['miniconf_url']
    miniconf_page_url = f'{miniconf_url}/poster_{paper["uid"]}'  # site serves extensionless URLs
    # short_url = miniconf_page_url.split('https://', 1)[-1]
    buf = []
    buf.append(f'Paper, Poster, and more: \n{miniconf_page_url}\n\n')
    buf.append('Authors: ')
    buf.append(paper['authors_and_affil'])
    buf.append('\n\n')
    buf.append(f'Presented at {conf_name}.')
    buf.append('\n\n')
    buf.append('Abstract: \n')
    buf.append(paper['abstract'])
    buf.append('\n')
    return ''.join(buf)


class SafetyError(ValueError):
    """An unsafe or ambiguous input; no further operations are permitted."""


def identifier(value: object, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]+', value):
        raise SafetyError(f'Malformed {label}: {value!r}')
    return value


def drive_id(value: object, allow_url: bool = False) -> str:
    if allow_url and isinstance(value, str) and value.startswith('https://'):
        url = urlparse(value)
        if url.netloc != 'drive.google.com' or url.fragment:
            raise SafetyError(f'Malformed Drive URL: {value!r}')
        match = re.fullmatch(r'/file/d/([A-Za-z0-9_-]+)(?:/view)?', url.path)
        query = parse_qs(url.query)
        if match and 'id' not in query:
            value = match[1]
        elif url.path in ('/open', '/uc') and len(query.get('id', [])) == 1:
            value = query['id'][0]
        else:
            raise SafetyError(f'Ambiguous Drive URL: {value!r}')
    return identifier(value, 'Google Drive ID')


def unique_object(pairs: list[tuple[str, Any]]) -> APIObject:
    result = dict[str, Any]()
    for key, value in pairs:
        if key in result:
            raise SafetyError(f'Duplicate JSON key: {key}')
        result[key] = value
    return result


def validate_local(
    csv_path: Path, video_dir: Path, caption_dir: Path,
) -> tuple[list[str], list[PaperRow], dict[str, PaperRow], bytes, dict[str, Path], dict[str, Path]]:
    original = csv_path.read_bytes()
    reader = csv.DictReader(io.StringIO(original.decode('utf-8-sig'), newline=''))
    fields = list(reader.fieldnames or [])
    if len(fields) != len(set(fields)) or not {'uid', 'raw_video'} <= set(fields):
        raise SafetyError('CSV requires unique columns including uid and raw_video')
    rows = list[PaperRow]()
    papers = dict[str, PaperRow]()
    for raw_row in reader:
        if None in raw_row or any(value is None for value in raw_row.values()):
            raise SafetyError('Malformed CSV row')
        # Required columns and cell shapes have been checked at the CSV boundary.
        row = cast(PaperRow, raw_row)
        rows.append(row)
        uid = identifier(row['uid'], 'paper UID')
        if uid in papers:
            raise SafetyError(f'Duplicate CSV UID: {uid}')
        # Papers without videos may have an empty Drive cell.
        if row['raw_video']:
            drive_id(row['raw_video'], allow_url=True)
        if row.get('raw_captions'):
            drive_id(row['raw_captions'], allow_url=True)
        papers[uid] = row
    recorded = json.loads((video_dir / 'download-state/video_urls.json').read_text(),
                          object_pairs_hook=unique_object)
    if not isinstance(recorded, dict):
        raise SafetyError('Download state must be a JSON object')
    def check_dir(directory: Path, kind: str, column: Literal['raw_video', 'raw_captions']) -> dict[str, Path]:
        mappings = dict[str, str]()
        for key, entry in recorded.items():
            # Entries are {"video": url, "captions": url}; either key is optional.
            if not isinstance(entry, dict):
                raise SafetyError(f'Invalid download-state entry: {key}')
            if kind not in entry:
                continue
            value = entry[kind]
            path = Path(key)
            if path.name != key:
                raise SafetyError(f'Invalid download-state filename: {key}')
            uid = identifier(path.stem if path.suffix else key, 'download UID')
            if uid in mappings:
                raise SafetyError(f'Duplicate download UID: {uid}')
            mappings[uid] = drive_id(value, allow_url=True)
        found = dict[str, Path]()
        for path in sorted(directory.iterdir()) if directory.exists() else []:
            # Stray files are fine; only files named after a papers.csv UID matter.
            uid = path.stem
            if not path.suffix or uid not in papers:
                continue
            if not path.is_file() or path.is_symlink():
                raise SafetyError(f'Unexpected local {kind} entry: {path}')
            if uid in found:
                raise SafetyError(f'Duplicate local {kind} UID: {uid}')
            found[uid] = path
            if uid not in mappings or not papers[uid].get(column):
                raise SafetyError(f'Missing {kind} provenance mapping for local UID: {uid}')
            if mappings[uid] != drive_id(papers[uid][column], allow_url=True):
                raise SafetyError(f'Drive {kind} provenance mismatch for local UID: {uid}')
        return found

    local_videos = check_dir(video_dir, 'video', 'raw_video')
    captions = check_dir(caption_dir, 'captions', 'raw_captions')
    return fields, rows, papers, original, local_videos, captions


def metadata(description: object) -> Metadata | None:
    if not isinstance(description, str):
        raise SafetyError('Video description is not a string')
    if 'ISMIR_METADATA' not in description:
        return None
    blocks = re.findall(r'(?:^|\n)---\nISMIR_METADATA\n(.*?)\s*\Z', description, re.S)
    if description.count('ISMIR_METADATA') != 1 or len(blocks) != 1:
        raise SafetyError('Malformed or ambiguous ISMIR_METADATA block')
    values = dict[str, str]()
    for line in blocks[0].splitlines():
        match = re.fullmatch(r'(paper_id|google_drive_id|caption_drive_id): ([A-Za-z0-9_-]+)', line)
        if not match or match[1] in values:
            raise SafetyError('Malformed or duplicate metadata field')
        values[match[1]] = match[2]
    if not {'paper_id', 'google_drive_id'} <= set(values):
        raise SafetyError('Metadata requires paper_id and google_drive_id')
    result = Metadata(paper_id=values['paper_id'], google_drive_id=values['google_drive_id'])
    if 'caption_drive_id' in values:
        result['caption_drive_id'] = values['caption_drive_id']
    return result


def execute(request: HttpRequest) -> APIObject:
    try:
        result = request.execute(num_retries=0)
    except Exception as exc:
        content = getattr(exc, 'content', b'')
        if any(reason in str(content) for reason in ('quotaExceeded', 'dailyLimitExceeded')):
            raise SafetyError('YouTube quota exhausted; aborted immediately') from exc
        raise SafetyError(f'YouTube request failed; aborted without retry: {exc}') from exc
    if request.method == 'DELETE' and result == '':  # 204 No Content
        return {}
    if not isinstance(result, dict):
        raise SafetyError('Unexpected API response')
    return result


def pages(resource: Resource, **kwargs: Any) -> Iterator[APIObject]:
    token = None
    seen = set[str]()
    while True:
        response = execute(resource.list(**kwargs, **({'pageToken': token} if token else {})))
        items = response.get('items')
        if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
            raise SafetyError('API response missing valid items')
        yield from items
        token = response.get('nextPageToken')
        if token is None:
            break
        if not isinstance(token, str) or not token or token in seen:
            raise SafetyError('Invalid/repeated pagination token')
        seen.add(token)


def enumerate_videos(youtube: Resource) -> list[APIObject]:
    if not re.fullmatch(r'UC[A-Za-z0-9_-]{22}', EXPECTED_CHANNEL_ID):
        raise SafetyError('Configure EXPECTED_CHANNEL_ID before calling YouTube')
    channels = list(pages(youtube.channels(), part='contentDetails', mine=True, maxResults=50))
    if len(channels) != 1 or channels[0].get('id') != EXPECTED_CHANNEL_ID:
        raise SafetyError('Authenticated channel does not exactly match EXPECTED_CHANNEL_ID')
    playlist = channels[0]['contentDetails']['relatedPlaylists']['uploads']
    if not isinstance(playlist, str) or not playlist:
        raise SafetyError('Missing uploads playlist')
    ids = list[str]()
    for item in pages(youtube.playlistItems(), part='contentDetails', playlistId=playlist, maxResults=50):
        video_id = item['contentDetails']['videoId']
        if not isinstance(video_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{11}', video_id) or video_id in ids:
            raise SafetyError('Invalid or duplicate upload playlist video ID')
        ids.append(video_id)
    videos = list[APIObject]()
    for start in range(0, len(ids), 50):
        batch = ids[start:start + 50]
        fetched = list(pages(youtube.videos(), part='snippet,status', id=','.join(batch), maxResults=50))
        if len(fetched) != len(batch) or {v.get('id') for v in fetched} != set(batch):
            raise SafetyError('Uploads playlist and videos response disagree')
        for video in fetched:
            if video['snippet']['channelId'] != EXPECTED_CHANNEL_ID:
                raise SafetyError('Video belongs to an unexpected channel')
            for key in ('title', 'description', 'categoryId'):
                if not isinstance(video['snippet'].get(key), str):
                    raise SafetyError(f'Missing video snippet.{key}')
            if video['status'].get('privacyStatus') not in ('private', 'unlisted', 'public'):
                raise SafetyError('Invalid video status')
        videos.extend(fetched)
    return videos


def mutable(video: APIObject) -> dict[str, APIObject]:
    return {part: {key: copy.deepcopy(value) for key, value in video[part].items() if key in keys}
            for part, keys in [('snippet', SNIPPET_FIELDS), ('status', STATUS_FIELDS)]}


def legalize(text: str, multiline: bool) -> str:
    """Make text acceptable to YouTube: no angle brackets or control characters."""
    text = text.replace('<', '‹').replace('>', '›')
    text = re.sub(r'\r\n?', '\n', text).replace('\t', ' ')
    text = ''.join(c for c in text if c == '\n' or unicodedata.category(c) != 'Cc')
    if not multiline:
        text = ' '.join(text.split())
    return text.strip()


def legalize_title(title: str) -> str:
    return legalize(title, multiline=False)[:100].rstrip()


def render(row: PaperRow, caption_drive_id: str | None) -> tuple[str, str]:
    title = legalize_title(generate_title(row))
    human = legalize(generate_description(row), multiline=True)
    if 'ISMIR_METADATA' in human:
        raise SafetyError('Human description template must not contain machine metadata')
    footer = ('\n\n---\nISMIR_METADATA\n'
              f"paper_id: {row['uid']}\ngoogle_drive_id: {drive_id(row['raw_video'], allow_url=True)}"
              + (f'\ncaption_drive_id: {caption_drive_id}' if caption_drive_id else ''))
    budget = 4999 - len(footer.encode('utf-8'))
    if len(human.encode('utf-8')) > budget:
        ellipsis = '…'
        cut = budget - len(ellipsis.encode('utf-8'))
        human = human.encode('utf-8')[:cut].decode('utf-8', 'ignore').rstrip() + ellipsis
    description = human + footer
    return title, description


def fresh_paper_id(video: APIObject, papers: Mapping[str, PaperRow]) -> str | None:
    """A fresh upload has an integer title naming its paper and an empty description."""
    title = video['snippet']['title'].strip()
    if video['snippet']['description'].strip() or not re.fullmatch(r'\d+', title):
        return None
    matches = [uid for uid in papers if uid == title or (uid.isdigit() and int(uid) == int(title))]
    if len(matches) != 1:
        raise SafetyError(f'Fresh upload {video["id"]} titled {title!r} matches '
                          f'{len(matches)} CSV papers; expected exactly 1')
    return matches[0]


def plan_updates(
    videos: Sequence[APIObject], papers: Mapping[str, PaperRow], captions: Mapping[str, Path],
) -> list[UpdatePlan]:
    # (video, is_current, claimed caption) per paper; fresh uploads are current by definition.
    by_paper = dict[str, list[tuple[APIObject, bool, str | None]]]()
    for video in videos:
        claim = metadata(video['snippet']['description'])
        if claim is None:
            uid = fresh_paper_id(video, papers)
            if uid is None:
                continue
            current = True
            claimed_caption = None
        else:
            uid = claim['paper_id']
            if uid not in papers:
                raise SafetyError(f'Managed paper absent from CSV: {uid}')
            current = claim['google_drive_id'] == drive_id(papers[uid]['raw_video'], allow_url=True)
            claimed_caption = claim.get('caption_drive_id')
        by_paper.setdefault(uid, []).append((video, current, claimed_caption))

    plans = list[UpdatePlan]()
    for uid, paper in papers.items():
        candidates = by_paper.get(uid, [])
        currents = [video['id'] for video, current, _ in candidates if current]
        if len(currents) > 1:
            raise SafetyError(f'!!! Multiple non-outdated YouTube videos for paper {uid}: '
                              f'{", ".join(currents)}. Archive or delete extras by hand. Aborting.')
        for video, current, claimed_caption in candidates:
            # Archived, private outdated uploads need no further changes.
            if not current and (video['status']['privacyStatus'] == 'private'
                                and video['snippet']['title'].startswith('[outdated]')):
                continue
            before = mutable(video)
            after = copy.deepcopy(before)
            caption: CaptionPlan | None = None
            if current:
                # The footer records the synced caption, so a match costs no caption API quota.
                wanted = drive_id(paper['raw_captions'], allow_url=True) if paper.get('raw_captions') else None
                if wanted != claimed_caption:
                    if wanted is not None and uid not in captions:
                        raise SafetyError(f'Captions for {uid} not downloaded; run the downloader first')
                    caption = {'drive_id': wanted, 'path': str(captions[uid]) if wanted else None}
                title, description = render(paper, wanted)
                after['snippet'].update(title=title, description=description,
                                        categoryId='28', defaultLanguage='en')
                after['status'].update(privacyStatus='unlisted', license='creativeCommon',
                                       selfDeclaredMadeForKids=False)
            else:
                if not after['snippet']['title'].startswith('[outdated]'):
                    after['snippet']['title'] = legalize_title('[outdated] ' + after['snippet']['title'])
                after['snippet'].setdefault('defaultLanguage', 'en')
                after['status']['privacyStatus'] = 'private'
            # A scheduled publication would defeat private/unlisted visibility.
            after['status'].pop('publishAt', None)
            if not after['snippet']['title'] or len(after['snippet']['title']) > 100:
                raise SafetyError(f'Invalid generated title length for {uid}')
            if len(after['snippet']['description'].encode('utf-8')) > 5000:
                raise SafetyError(f'Generated description exceeds 5000 bytes for {uid}')
            body = {'id': video['id'], **{p: after[p] for p in after if before[p] != after[p]}}
            url = f"https://www.youtube.com/watch?v={video['id']}" if current else None
            plans.append({'uid': uid, 'body': body, 'before': before, 'url': url,
                          'classification': 'current' if current else 'outdated', 'caption': caption})
    return plans


def missing_videos(videos: Sequence[APIObject], papers: Mapping[str, PaperRow]) -> list[str]:
    """Papers with a raw_video but no current YouTube upload, whether outdated or never uploaded."""
    present = set[str]()
    for video in videos:
        claim = metadata(video['snippet']['description'])
        if claim is None:
            uid = fresh_paper_id(video, papers)
            if uid is not None:
                present.add(uid)
        elif claim['google_drive_id'] == drive_id(papers[claim['paper_id']]['raw_video'], allow_url=True):
            present.add(claim['paper_id'])
    return [uid for uid, row in papers.items() if row['raw_video'] and uid not in present]


def summarize_coverage(rows: Sequence[PaperRow]) -> None:
    def count(raw: bool, vid: bool) -> int:
        return sum(bool(row['raw_video']) == raw and bool(row.get('video')) == vid for row in rows)
    print(f'papers.csv coverage ({len(rows)} papers):')
    print('                   video set  video empty')
    print(f'  raw_video set    {count(True, True):>9}  {count(True, False):>11}')
    print(f'  raw_video empty  {count(False, True):>9}  {count(False, False):>11}')


def atomic_write(path: Path, data: bytes, mode: int | None = None) -> None:
    fd, name = tempfile.mkstemp(dir=path.parent, prefix=f'.{path.name}-')
    try:
        with os.fdopen(fd, 'wb') as stream:
            if mode is not None:
                os.fchmod(stream.fileno(), mode)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def caption_name(caption_drive_id: str) -> str:
    # 5 base62 chars (~29.8 bits): 95% chance that each of 300 years sees no collision among its 300 IDs.
    alphabet = '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz'
    number = int.from_bytes(hashlib.sha256(caption_drive_id.encode()).digest(), 'big')
    digits = list[str]()
    for _ in range(5):
        number, digit = divmod(number, 62)
        digits.append(alphabet[digit])
    return f'official ({"".join(digits)})'


def sync_captions(youtube: Resource, video_id: str, caption: CaptionPlan) -> None:
    """Insert before deleting so a crash leaves duplicates of ours at worst, which the rerun cleans."""
    from googleapiclient.http import MediaFileUpload

    wanted = caption['drive_id']
    tracks = list(pages(youtube.captions(), part='snippet', videoId=video_id))
    ours = [t for t in tracks if re.fullmatch(CAPTION_NAME_PATTERN, str(t['snippet'].get('name', '')))]
    name = caption_name(wanted) if wanted is not None else None
    keep = [t for t in ours if name is not None and t['snippet'].get('name') == name]
    if len(keep) > 1:
        raise SafetyError(f'Multiple caption tracks named {name} on {video_id}; delete extras by hand')
    if wanted is not None and not keep:
        assert caption['path'] is not None
        snippet = {'videoId': video_id, 'language': 'en', 'name': name, 'isDraft': False}
        response = execute(youtube.captions().insert(
            part='snippet', body={'snippet': snippet},
            media_body=MediaFileUpload(caption['path'], mimetype='application/octet-stream')))
        if response.get('snippet', {}).get('name') != name or not response.get('id'):
            raise SafetyError('Caption insert response differs from request')
        keep = [response]
        tqdm.write(f'COMPLETED caption insert: {video_id} {name}')
    for track in ours:
        if track['id'] not in {t['id'] for t in keep}:
            execute(youtube.captions().delete(id=track['id']))
            tqdm.write(f"COMPLETED caption delete: {video_id} {track['snippet'].get('name')}")


def apply_updates(
    youtube: Resource, plans: Sequence[UpdatePlan], csv_path: Path,
    fields: list[str], rows: list[PaperRow], original: bytes, videos: Sequence[APIObject],
    dry_run: bool = False,
) -> None:
    """Applied changes are mirrored into `videos`, so the playlist sync needs no re-read."""
    papers = {row['uid']: row for row in rows}
    videos_by_id = {video['id']: video for video in videos}
    for plan in tqdm(plans, desc='Videos', unit='video'):
        body = plan['body']
        parts = [part for part in ('snippet', 'status') if part in body]
        url = plan['url']
        csv_change = url is not None and papers[plan['uid']].get('video', '') != url
        caption = plan['caption']
        if not parts and not csv_change and caption is None:
            continue
        if csv_path.read_bytes() != original:
            raise SafetyError('CSV changed during execution; aborting')
        log = {**plan, 'csv_video_before': papers[plan['uid']].get('video', ''),
               'csv_video_after': plan['url'] if csv_change else None}
        tqdm.write(('DRY RUN ' if dry_run else 'PLANNED ') + json.dumps(log, ensure_ascii=False, sort_keys=True))
        if dry_run:
            for part in parts:
                videos_by_id[body['id']][part].update(body[part])
            continue
        if caption is not None:
            # Before the description update, which records the caption in the footer.
            sync_captions(youtube, body['id'], caption)
        if parts:
            response = execute(youtube.videos().update(part=','.join(parts), body=body))
            if response.get('id') != body['id'] or any(
                {k: response.get(p, {}).get(k) for k in body[p]} != body[p] for p in parts
            ) or any('publishAt' in response.get(p, {}) and 'publishAt' not in body[p] for p in parts):
                raise SafetyError('Update response differs from request; remote state may have changed')
            for part in parts:
                videos_by_id[body['id']][part].update(body[part])
            tqdm.write(f"COMPLETED YouTube {plan['classification']} update: {body['id']}")
        if csv_change and url is not None:
            if csv_path.read_bytes() != original:
                raise SafetyError('CSV changed during YouTube update; aborting')
            papers[plan['uid']]['video'] = url
            if 'video' not in fields:
                fields = [*fields, 'video']
            stream = io.StringIO(newline='')
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
            updated = stream.getvalue().encode('utf-8-sig' if original.startswith(b'\xef\xbb\xbf') else 'utf-8')
            atomic_write(csv_path, updated, csv_path.stat().st_mode & 0o777)
            original = updated
            tqdm.write(f"COMPLETED CSV video update: {plan['uid']} -> {plan['url']}")


class PlaylistState(TypedDict):
    id: str
    title: str
    description: str
    privacyStatus: str
    # (playlistItem ID, video ID) in playlist order.
    items: list[tuple[str, str]]


def playlist_key(description: object) -> str | None:
    if not isinstance(description, str):
        raise SafetyError('Playlist description is not a string')
    if 'ISMIR_PLAYLIST' not in description:
        return None
    keys = re.findall(r'(?:^|\n)---\nISMIR_PLAYLIST\nkey: (all|session-[1-9][0-9]*)\Z', description)
    if description.count('ISMIR_PLAYLIST') != 1 or len(keys) != 1:
        raise SafetyError('Malformed or ambiguous ISMIR_PLAYLIST block')
    return keys[0]


def enumerate_playlists(youtube: Resource) -> dict[str, PlaylistState]:
    playlists = dict[str, PlaylistState]()
    for playlist in pages(youtube.playlists(), part='snippet,status', mine=True, maxResults=50):
        if playlist['snippet'].get('channelId') != EXPECTED_CHANNEL_ID:
            raise SafetyError('Playlist belongs to an unexpected channel')
        key = playlist_key(playlist['snippet'].get('description'))
        if key is None:
            continue
        if key in playlists:
            raise SafetyError(f'Multiple playlists with key {key}; delete extras by hand')
        playlist_id = identifier(playlist['id'], 'playlist ID')
        items = [(identifier(item['id'], 'playlist item ID'),
                  identifier(item['snippet']['resourceId'].get('videoId'), 'video ID'))
                 for item in pages(youtube.playlistItems(), part='snippet',
                                   playlistId=playlist_id, maxResults=50)]
        playlists[key] = {'id': playlist_id, 'title': playlist['snippet']['title'],
                          'description': playlist['snippet']['description'],
                          'privacyStatus': playlist['status']['privacyStatus'], 'items': items}
    return playlists


def desired_playlists(
    videos: Sequence[APIObject], papers: Mapping[str, PaperRow],
) -> dict[str, tuple[str, str, list[str]]]:
    """Key -> (title, description, video IDs in order). Only decorated, current videos are listed."""
    current = dict[str, str]()
    for video in videos:
        claim = metadata(video['snippet']['description'])
        if claim is None:
            continue
        paper = papers[claim['paper_id']]
        if paper['raw_video'] and claim['google_drive_id'] == drive_id(paper['raw_video'], allow_url=True):
            current[claim['paper_id']] = video['id']
    sessions, _ = parse_file('./sitedata/')
    config = load_site_config('./sitedata/')
    conf_name = config['name']
    link = f"Paper, Poster, and more: \n{config['miniconf_url']}"

    def entry(key: str, label: str, scope: str, uids: Sequence[str]) -> tuple[str, str, list[str]]:
        title = legalize_title(f'{conf_name} Presentation Videos - {label}')
        human = legalize(f'Presentation videos of {scope} at {conf_name}.\n\n{link}', multiline=True)
        return title, f'{human}\n\n---\nISMIR_PLAYLIST\nkey: {key}', [current[u] for u in uids if u in current]

    # Session.name is internal; only the index is shown.
    result = {f'session-{s.index}': entry(f'session-{s.index}', f'Paper Session {s.index}',
                                          f'Paper Session {s.index}', s.papers) for s in sessions}
    result['all'] = entry('all', 'All Papers', 'all papers',
                          [uid for s in sessions for uid in s.papers])
    return result


def longest_increasing(ranks: Sequence[int]) -> set[int]:
    """Ranks forming a longest increasing subsequence; these items need not move."""
    length = [1] * len(ranks)
    prev = [-1] * len(ranks)
    for i in range(len(ranks)):
        for j in range(i):
            if ranks[j] < ranks[i] and length[j] + 1 > length[i]:
                length[i], prev[i] = length[j] + 1, j
    i = max(range(len(ranks)), key=length.__getitem__, default=-1)
    result = set[int]()
    while i != -1:
        result.add(ranks[i])
        i = prev[i]
    return result


def sync_playlists(
    youtube: Resource, playlists: dict[str, PlaylistState], videos: Sequence[APIObject],
    papers: Mapping[str, PaperRow], dry_run: bool = False,
) -> None:
    """Items whose video is not ours and decorated are unmanaged and left in place."""
    managed = {v['id'] for v in videos if metadata(v['snippet']['description']) is not None}
    prefix = 'DRY RUN ' if dry_run else 'PLANNED '

    def log(message: str) -> None:
        tqdm.write(f'{prefix}playlist {message}')

    for key, (title, description, wanted) in desired_playlists(videos, papers).items():
        snippet = {'title': title, 'description': description}
        state = playlists.get(key)
        if state is None:
            if not wanted:
                continue
            log(f'create {key}: {title}')
            playlist_id = f'DRY-{key}'
            if not dry_run:
                response = execute(youtube.playlists().insert(
                    part='snippet,status', body={'snippet': snippet, 'status': {'privacyStatus': 'public'}}))
                playlist_id = identifier(response.get('id'), 'playlist ID')
                if playlist_key(response.get('snippet', {}).get('description')) != key:
                    raise SafetyError('Playlist insert response differs from request')
                tqdm.write(f'COMPLETED playlist create: {key} {playlist_id}')
            state = playlists[key] = {'id': playlist_id, 'title': title, 'description': description,
                                      'privacyStatus': 'public', 'items': []}
        elif (state['title'], state['description'], state['privacyStatus']) != (title, description, 'public'):
            log(f'update {key}: {title}')
            if not dry_run:
                response = execute(youtube.playlists().update(part='snippet,status', body={
                    'id': state['id'], 'snippet': snippet, 'status': {'privacyStatus': 'public'}}))
                if response.get('id') != state['id']:
                    raise SafetyError('Playlist update response differs from request')
                tqdm.write(f'COMPLETED playlist update: {key}')
            state.update(title=title, description=description, privacyStatus='public')

        items = state['items']
        seen = set[str]()
        for item in list(items):
            item_id, video_id = item
            if video_id in managed and (video_id not in wanted or video_id in seen):
                log(f'remove {key}: {video_id}')
                if not dry_run:
                    execute(youtube.playlistItems().delete(id=item_id))
                    tqdm.write(f'COMPLETED playlist remove: {key} {video_id}')
                items.remove(item)
            seen.add(video_id)

        rank = {video_id: i for i, video_id in enumerate(wanted)}
        stable = longest_increasing([rank[v] for _, v in items if v in rank])
        # Placing each item right after its predecessor, in order, yields the wanted order.
        for i, video_id in enumerate(wanted):
            if i in stable:
                continue
            existing = [item for item in items if item[1] == video_id]
            for item in existing:
                items.remove(item)
            ids = [v for _, v in items]
            position = (ids.index(wanted[i - 1]) + 1 if i
                        else next((j for j, v in enumerate(ids) if v in managed), 0))
            item_snippet = {'playlistId': state['id'], 'position': position,
                            'resourceId': {'kind': 'youtube#video', 'videoId': video_id}}
            log(f"{'move' if existing else 'insert'} {key}: {video_id} -> {position}")
            item_id = existing[0][0] if existing else f'DRY-{key}-{video_id}'
            if not dry_run:
                if existing:
                    request = youtube.playlistItems().update(
                        part='snippet', body={'id': item_id, 'snippet': item_snippet})
                else:
                    request = youtube.playlistItems().insert(part='snippet', body={'snippet': item_snippet})
                response = execute(request)
                item_id = identifier(response.get('id'), 'playlist item ID')
                if response.get('snippet', {}).get('position') != position:
                    raise SafetyError('Playlist item response differs from request')
                tqdm.write(f'COMPLETED playlist {"move" if existing else "insert"}: {key} {video_id}')
            items.insert(position, (item_id, video_id))


def authenticate() -> Resource:
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    client_id = os.environ.get('google_client_id')
    client_secret = os.environ.get('google_client_secret')
    if not client_id or not client_secret:
        raise SafetyError('Set env vars google_client_id and google_client_secret')
    flow = InstalledAppFlow.from_client_config({'installed': {
        'client_id': client_id,
        'client_secret': client_secret,
        'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
        'token_uri': 'https://oauth2.googleapis.com/token',
    }}, SCOPES)
    credentials = flow.run_local_server(port=0)
    return build('youtube', 'v3', credentials=credentials, cache_discovery=False)


def main(argv: Sequence[str] | None = None) -> int:
    rows: Sequence[PaperRow] = ()
    try:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument('--input', type=Path, default=ROOT / 'sitedata/papers.csv')
        parser.add_argument('--videos', type=Path, default=ROOT / 'tmp/videos')
        parser.add_argument('--captions', type=Path, default=ROOT / 'tmp/captions')
        parser.add_argument('--dry-run', action='store_true', help='Read and plan only; no CSV or YouTube writes')
        parser.add_argument('--drier-run', action='store_true',
                            help='No auth or API calls; pretend YouTube is empty and print the plan')
        parser.add_argument('--first-video', action='store_true',
                            help='Apply only the first planned update, for testing')
        parser.add_argument('--no-playlists', action='store_true', help='Skip playlist sync')
        args = parser.parse_args(argv)
        dry_run = args.dry_run or args.drier_run
        fields, rows, papers, original, local_videos, captions = validate_local(args.input, args.videos, args.captions)
        if args.drier_run:
            print('DRIER RUN: no auth or API calls; pretending YouTube has no uploads.')
            youtube = cast('Resource', None)
            videos = list[APIObject]()
            playlists = dict[str, PlaylistState]()
        else:
            if not re.fullmatch(r'UC[A-Za-z0-9_-]{22}', EXPECTED_CHANNEL_ID):
                raise SafetyError('Set EXPECTED_CHANNEL_ID to the verified channel ID')
            youtube = authenticate()
            videos = enumerate_videos(youtube)
            playlists = {} if args.no_playlists else enumerate_playlists(youtube)
        managed = sum(metadata(v['snippet']['description']) is not None for v in videos)
        fresh = sum(metadata(v['snippet']['description']) is None
                    and fresh_paper_id(v, papers) is not None for v in videos)
        print(f'Found {len(videos)} uploads: {managed} with ISMIR_METADATA, {fresh} fresh, '
              f'{len(videos) - managed - fresh} unrelated and ignored.')
        plans = plan_updates(videos, papers, captions)
        print(f'Planned {len(plans)} videos; ones needing no change are skipped silently.')
        if args.first_video:
            plans = plans[:1]
            print(f'FIRST VIDEO: limiting to {len(plans)} update.')
        apply_updates(youtube, plans, args.input, fields, rows, original, videos, dry_run)
        if not args.no_playlists:
            sync_playlists(youtube, playlists, videos, papers, dry_run)
        if dry_run:
            print('DRY RUN: coverage below is the unchanged CSV.')
        summarize_coverage(rows)
        missing = missing_videos(videos, papers)
        print(f'Papers with raw_video but no current YouTube upload ({len(missing)}); upload by hand:')
        for uid in missing:
            print(f'  {uid}')
        if paths := [str(local_videos[uid]) for uid in missing if uid in local_videos]:
            for start in range(0, len(paths), 15):
                try:
                    subprocess.run(['dragon-drop', '--all', *paths[start:start + 15]], check=False)
                except OSError as e:
                    print(f'dragon-drop failed: {e}')
        return 0
    finally:
        if rows:
            pyperclip.copy('\n'.join(['video', *(row.get('video', '') for row in rows)]))
            print('Copied the video column (with header, in papers.csv row order). '
                  'Paste it into the video header cell in Google Sheets.')


if __name__ == '__main__':
    raise SystemExit(main())
