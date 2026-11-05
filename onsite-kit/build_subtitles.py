"""Build one WebVTT subtitle file per LBD video, for the Drive folder DRIVE_FOLDER_SUBTITLES.

Run on an organizer's machine that has downloaded every video and caption file (Materials), with ffmpeg:
    python3 onsite-kit/build_subtitles.py [youtube_captions_dir]
It writes local/subtitles/<uid>.vtt. Upload those files to the subtitles folder, replacing the old ones;
each MacBook then downloads them in Materials like any other file.

For each video, the first source found wins: the authors' caption file from Drive (.srt or .sbv, maybe
zipped), the subtitle track inside the video, then YouTube's automatic captions (yt-dlp's <uid>.en-orig.vtt).
Videos with subtitles in the picture get no file, so nothing is drawn over them.
"""

import html
import re
import subprocess
import sys
import zipfile
from pathlib import Path

KIT = Path(__file__).resolve().parent
MEDIA = KIT / 'media'
OUT = KIT.parent / 'local' / 'subtitles'
# Subtitles already in the picture, seen on frames of every video (November 2026).
BURNED_IN = set('''571 575 578 583 585 586 589 590 591 602 604 608 609 610 613 617 624 632 633 636 637 639 640
641 644 645 649 650 651 652 653 662 664 665 671 673 685 m2 m3 m4 m5 m7 m8 m10 m11'''.split())
TIME = re.compile(r'(\d+):(\d\d):(\d\d)[.,](\d{3})')
CUE_TIME = re.compile(r'([\d:.,]+) --> ([\d:.,]+)')


def stamp(seconds: float) -> str:
    ms = round(seconds * 1000)
    return f'{ms // 3_600_000:02}:{ms // 60_000 % 60:02}:{ms // 1000 % 60:02}.{ms % 1000:03}'


def seconds(text: str) -> float:
    parts = [int(p) for p in re.split(r'[:.,]', text)]
    if len(parts) == 3:  # m:ss.mmm
        parts = [0] + parts
    hours, minutes, secs, ms = parts
    return hours * 3600 + minutes * 60 + secs + ms / 1000


def vtt(cues: list) -> str:
    return 'WEBVTT\n\n' + ''.join(f'{stamp(start)} --> {stamp(end)}\n{text}\n\n' for start, end, text in cues if text.strip())


def parse_blocks(text: str) -> list:
    """Cues of an SRT, SBV or WebVTT file: (start, end, text)."""
    cues = []
    for block in re.split(r'\n\n+', text.replace('\r', '').replace('﻿', '')):
        lines = block.strip('\n').split('\n')
        for index, line in enumerate(lines):
            times = CUE_TIME.search(line) or (re.fullmatch(r'([\d:.]+),([\d:.]+)', line.strip()))  # SBV: start,end
            if times:
                cues.append((seconds(times[1]), seconds(times[2]), '\n'.join(lines[index + 1:]).strip()))
                break
    return cues


def from_caption_file(uid: str):
    files = [f for f in (MEDIA / 'captions').glob(f'{uid}.*') if f.stem == uid]
    if not files:
        return None
    file = files[0]
    if file.suffix == '.zip':
        with zipfile.ZipFile(file) as archive:
            name = next(n for n in archive.namelist() if n.lower().endswith(('.srt', '.sbv', '.vtt')))
            return parse_blocks(archive.read(name).decode('utf-8-sig', errors='replace'))
    return parse_blocks(file.read_text(encoding='utf-8-sig', errors='replace'))


def from_track(video: Path):
    done = subprocess.run(['ffmpeg', '-v', 'error', '-i', str(video), '-map', '0:s:0', '-f', 'webvtt', '-'],
                          capture_output=True, text=True, encoding='utf-8', errors='replace')
    cues = parse_blocks(done.stdout) if done.returncode == 0 else []
    return cues or None


def from_youtube(folder: Path, uid: str):
    """YouTube's automatic captions roll: each cue repeats the line before. Keep the cues that last, as shown."""
    file = folder / f'{uid}.en-orig.vtt'
    if not file.exists():
        return None
    cues = []
    for start, end, text in parse_blocks(file.read_text(encoding='utf-8')):
        lines = [html.unescape(re.sub(r'<[^>]+>', '', line)).strip() for line in text.split('\n')]
        lines = [line for line in lines if line]
        if end - start > 0.05 and lines:
            cues.append((start, end, '\n'.join(lines)))
    return cues or None


def main():
    youtube = Path(sys.argv[1]) if len(sys.argv) > 1 else KIT.parent / 'local' / 'youtube_captions'
    OUT.mkdir(parents=True, exist_ok=True)
    for old in OUT.glob('*.vtt'):
        old.unlink()
    videos = sorted((MEDIA / 'videos').iterdir(), key=lambda f: (f.stem.startswith('m'), int(f.stem.lstrip('m'))))
    counts = {}
    for video in videos:
        uid = video.stem
        source, cues = 'in the picture', None
        if uid not in BURNED_IN:
            for source, make in (('caption file', lambda: from_caption_file(uid)), ('video track', lambda: from_track(video)),
                                 ('YouTube', lambda: from_youtube(youtube, uid)), ('none', lambda: None)):
                cues = make()
                if cues:
                    break
        if cues:
            (OUT / f'{uid}.vtt').write_text(vtt(cues), encoding='utf-8')
        counts.setdefault(source, []).append(uid)
    for source, uids in counts.items():
        print(f'{source}: {len(uids)}  {" ".join(uids)}')
    print(f'Wrote {sum(1 for _ in OUT.glob("*.vtt"))} files to {OUT}')


if __name__ == '__main__':
    main()
