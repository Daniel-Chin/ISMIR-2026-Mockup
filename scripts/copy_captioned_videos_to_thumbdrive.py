'''
uv run python -m scripts.copy_captioned_videos_to_thumbdrive /run/media/dan/THUMBDRIVE
Copies output of scripts.bake_captions.
Writes <drive>/videos_w_caption/session-xx/Pxx-yy.{ext}, xx = session index, yy = position.
`*-too-long.*` files are skipped; each has a plain (trimmed) counterpart.
'''
import os
import sys
import shutil

from utils.session_assignment import parse_file

SITEDATA = './sitedata/'
VIDEOS_DIR = './tmp/videos_w_caption/'

def find_video(uid: str) -> str | None:
    for name in os.listdir(VIDEOS_DIR):
        stem, _ = os.path.splitext(name)
        if stem == uid:
            return os.path.join(VIDEOS_DIR, name)
    return None

def main(drive: str):
    _, papers = parse_file(SITEDATA)
    missing = []
    for paper in papers:
        if not paper.uid:   # empty slot in the assignment matrix
            continue
        src = find_video(paper.uid)
        if src is None:
            missing.append(paper.uid)
            continue
        ext = os.path.splitext(src)[1]
        session_dir = os.path.join(drive, 'videos_w_caption', f'session-{paper.session_index:02d}')
        os.makedirs(session_dir, exist_ok=True)
        dst = os.path.join(session_dir, f'P{paper.session_index:02d}-{paper.position:02d}{ext}')
        if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src):
            print('skip (exists)', dst)
            continue
        print(src, '->', dst, end=' ', flush=True)
        shutil.copyfile(src, dst)   # no metadata copy; FAT/exFAT rejects chmod
        # flush page cache to the device so progress reflects real writes
        with open(dst, 'rb+') as f:
            os.fsync(f.fileno())
        print('done', flush=True)
    if missing:
        print('No video for uids:', ', '.join(missing))

if __name__ == '__main__':
    main(sys.argv[1])
