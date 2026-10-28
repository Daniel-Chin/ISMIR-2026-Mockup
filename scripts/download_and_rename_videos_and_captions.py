"""
Download Google Drive videos and captions sequentially through the Drive API,
naming them by paper uid. Needs env vars google_client_id and google_client_secret
and a browser login to any Google account that can read the files.
uv run python -m scripts.download_and_rename_videos_and_captions --uids 13,139
"""

import argparse
import csv
import json
import os
import re
from pathlib import Path
from tempfile import TemporaryDirectory

from tqdm import tqdm

from utils.live_database import google_credentials


ROOT = Path(__file__).resolve().parent.parent
IN_CSV = ROOT / 'sitedata/papers.csv'
OUT_DIR = ROOT / 'tmp/videos'
CAPTIONS_OUT_DIR = ROOT / 'tmp/captions'

# kind -> (CSV column, minimum plausible file size in bytes)
KINDS = {
    'video': ('raw_video', 1024),
    'captions': ('raw_captions', 1),
}


def atomic_write(path: Path, contents: str) -> None:
    """Replace a state file without exposing partially written contents."""
    with TemporaryDirectory(dir=path.parent, prefix='.write-') as temp:
        staged = Path(temp) / path.name
        with staged.open('w', encoding='utf-8') as target:
            target.write(contents)
            target.flush()
            os.fsync(target.fileno())
        staged.replace(path)


def authenticate():
    """A Drive API client, after a browser login (the URL is printed)."""
    from googleapiclient.discovery import build

    credentials = google_credentials(['https://www.googleapis.com/auth/drive.readonly'])
    return build('drive', 'v3', credentials=credentials, cache_discovery=False)


def drive_file_id(url: str) -> str:
    match = re.search(r'[?&]id=([\w-]+)', url) or re.search(r'/file/d/([\w-]+)', url)
    if not match:
        raise ValueError(f'Not a Google Drive file link: {url}')
    return match.group(1)


def drive_download(drive, url: str, directory: Path) -> Path:
    """Download the Drive file at url into directory under its Drive filename."""
    from googleapiclient.http import MediaIoBaseDownload

    file_id = drive_file_id(url)
    name = drive.files().get(fileId=file_id, fields='name', supportsAllDrives=True).execute()['name']
    path = directory / (Path(name).name or file_id)
    with path.open('wb') as target:
        downloader = MediaIoBaseDownload(
            target, drive.files().get_media(fileId=file_id, supportsAllDrives=True), chunksize=32 * 1024 * 1024)
        done = False
        while not done:
            _, done = downloader.next_chunk(num_retries=3)
    return path


def load_local_urls(urls_path: Path) -> dict[str, dict[str, str]]:
    """Load {uid: {kind: url}}; legacy {uid: video_url} entries are upgraded."""
    raw = json.loads(urls_path.read_text(encoding='utf-8')) if urls_path.exists() else {}
    if not isinstance(raw, dict):
        raise ValueError(f'Invalid URL map: {urls_path}')
    local_urls = {}
    for uid, entry in raw.items():
        if isinstance(entry, str):
            entry = {'video': entry}
        if not isinstance(uid, str) or not isinstance(entry, dict) or not all(
            kind in KINDS and isinstance(url, str) for kind, url in entry.items()
        ):
            raise ValueError(f'Invalid URL map: {urls_path}')
        local_urls[uid] = entry
    return local_urls


def download_videos(in_csv: Path, out_dir: Path, captions_out_dir: Path, uids: set[str] | None = None) -> int:
    """Track local URLs and log successful downloads; skip blank cells, and
    papers not in uids when it is given.

    download-state/video_urls.json (in out_dir) records, per uid, the URLs of
    downloaded local files: {uid: {"video": url, "captions": url}}, either key
    optional. download-state/new_videos.log and new_captions.log are replaced
    each run with successful UIDs, one per line (including first downloads).
    Run only one downloader at a time.
    """
    with in_csv.open(newline='', encoding='utf-8-sig') as source:
        reader = csv.DictReader(source)
        if not {'uid', 'raw_video', 'raw_captions'} <= set(reader.fieldnames or []):
            raise ValueError('CSV must contain uid, raw_video and raw_captions columns')
        rows = list(reader)
    if uids is not None:
        unknown = uids - {(row.get('uid') or '').strip() for row in rows}
        if unknown:
            raise ValueError(f'Unknown paper uids: {sorted(unknown)}')
        rows = [row for row in rows if (row.get('uid') or '').strip() in uids]

    dirs = {'video': out_dir, 'captions': captions_out_dir}
    jobs = []
    for kind, (column, _) in KINDS.items():
        seen = set()
        for row in rows:
            paper_id = (row.get('uid') or '').strip()
            url = (row.get(column) or '').strip()
            if not url:
                continue
            if not re.fullmatch(r'[A-Za-z0-9_-]+', paper_id):
                raise ValueError(f'Invalid paper uid: {paper_id!r}')
            if paper_id in seen:
                raise ValueError(f'Duplicate paper uid: {paper_id!r}')
            seen.add(paper_id)
            jobs.append((paper_id, kind, url))

    for directory in dirs.values():
        directory.mkdir(parents=True, exist_ok=True)
    state_dir = out_dir / 'download-state'
    state_dir.mkdir(exist_ok=True)
    urls_path = state_dir / 'video_urls.json'
    local_urls = load_local_urls(urls_path)

    def save() -> None:
        atomic_write(urls_path, json.dumps(local_urls, indent=2, sort_keys=True) + '\n')

    save()
    new_files = {kind: [] for kind in KINDS}
    failures = 0
    skipped = 0
    pending = []
    for paper_id, kind, url in jobs:
        try:
            local_files = [
                path for path in dirs[kind].glob(f'{paper_id}.*')
                if path.stem == paper_id and path.is_file()
            ]
            if local_urls.get(paper_id, {}).get(kind) == url and any(
                path.stat().st_size >= KINDS[kind][1] for path in local_files
            ):
                skipped += 1
                continue
            pending.append((paper_id, kind, url, local_files))
        except Exception as exc:
            failures += 1
            tqdm.write(f'Failed uid={paper_id} {kind}: {exc}')

    drive = authenticate() if pending else None
    consecutive_failures = 0
    attempted = 0
    with tqdm(pending, desc='Files', unit='file') as progress:
        for paper_id, kind, url, local_files in progress:
            attempted += 1
            progress.set_postfix_str(f'uid={paper_id} {kind}')
            try:
                # Persist invalidation before touching any existing file.
                entry = local_urls.get(paper_id, {})
                entry.pop(kind, None)
                if entry:
                    local_urls[paper_id] = entry
                else:
                    local_urls.pop(paper_id, None)
                save()
                for path in local_files:
                    path.unlink()
                # Retain Drive's filename until its extension is known. Only
                # publish the final name once the download has completed.
                with TemporaryDirectory(dir=dirs[kind], prefix=f'.{paper_id}-') as temp:
                    file = drive_download(drive, url, Path(temp))
                    if not file.suffix and kind == 'captions':
                        file = file.rename(file.with_name(file.name + '.srt'))
                    if not file.suffix:
                        raise ValueError('Google Drive filename has no extension')
                    min_size = KINDS[kind][1]
                    if file.stat().st_size < min_size:
                        raise ValueError(f'Downloaded {kind} is smaller than {min_size} bytes')
                    file.replace(dirs[kind] / f'{paper_id}{file.suffix}')
                local_urls[paper_id] = {**entry, kind: url}
                save()
                new_files[kind].append(paper_id)
                consecutive_failures = 0
            except Exception as exc:
                failures += 1
                consecutive_failures += 1
                tqdm.write(f'Failed uid={paper_id} {kind}: {exc}')
                if consecutive_failures >= 3:
                    tqdm.write('Stopping after 3 consecutive failures.')
                    break

    for kind, log_name in (('video', 'new_videos.log'), ('captions', 'new_captions.log')):
        atomic_write(state_dir / log_name, ''.join(f'{uid}\n' for uid in new_files[kind]))
    tqdm.write(
        f'Downloaded {len(new_files["video"])} videos to {out_dir} and '
        f'{len(new_files["captions"])} captions to {captions_out_dir}; '
        f'skipped {skipped}, failed {failures}, not attempted {len(pending) - attempted}'
    )
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=IN_CSV, help='Input CSV path')
    parser.add_argument('--output', type=Path, default=OUT_DIR, help='Video output directory')
    parser.add_argument('--captions-output', type=Path, default=CAPTIONS_OUT_DIR,
                        help='Captions output directory')
    parser.add_argument('--uids', help='Comma-separated paper uids to download (default: all)')
    args = parser.parse_args()
    uids = {uid.strip() for uid in args.uids.split(',') if uid.strip()} if args.uids else None
    return 1 if download_videos(args.input, args.output, args.captions_output, uids) else 0


if __name__ == '__main__':
    raise SystemExit(main())
