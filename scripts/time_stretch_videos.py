"""
Uniformly speed up downloaded videos that are too long so they last exactly
TARGET_DURATION. The original is kept as "{uid}-too-long.{ext}" and the result
is re-encoded to "{uid}.mp4" (H.264 + AAC). The video's captions, if any, are
retimed by the same speed; the original is kept as "{uid}-too-long.{ext}".

The downloader's video_urls.json treats "{uid}.*" as the local copy of a uid,
so a too-long video is renamed away before the stretched one is published.
"""

import argparse
import re
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.download_and_rename_videos_and_captions import CAPTIONS_OUT_DIR, OUT_DIR
from scripts.police_videos import probe_duration


TOO_LONG = 3 * 60 + 10  # seconds
TARGET_DURATION = 3 * 60  # seconds
TOO_LONG_SUFFIX = '-too-long'
CAPTION_TIME = re.compile(r'(\d+):(\d\d):(\d\d)([,.])(\d{3})')


def stretch(src: Path, dst: Path, speed: float) -> None:
    """Encode src sped up by `speed` into dst, atomically."""
    with TemporaryDirectory(dir=dst.parent, prefix=f'.{dst.stem}-') as temp:
        staged = Path(temp) / dst.name
        subprocess.run(
            [
                'ffmpeg', '-v', 'error', '-y', '-i', str(src),
                '-filter:v', f'setpts=PTS/{speed}',
                '-filter:a', f'atempo={speed}',
                '-c:v', 'libx264', '-preset', 'medium', '-crf', '20', '-pix_fmt', 'yuv420p',
                '-c:a', 'aac', '-b:a', '160k',
                '-movflags', '+faststart',
                str(staged),
            ],
            check=True,
        )
        staged.replace(dst)


def stretch_caption_time(match: re.Match[str], speed: float) -> str:
    hours, minutes, seconds, separator, millis = match.groups()
    total = round((int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000) / speed * 1000)
    return (f'{total // 3600000:02d}:{total // 60000 % 60:02d}:{total // 1000 % 60:02d}'
            f'{separator}{total % 1000:03d}')


def stretch_captions(path: Path, speed: float) -> None:
    """Retime the cues of an SRT or VTT file; the original moves to "{uid}-too-long.{ext}"."""
    # Bytes, so that line endings and any BOM stay as they are.
    lines = path.read_bytes().decode('utf-8').split('\n')
    cues = 0
    for i, line in enumerate(lines):
        if '-->' in line:
            lines[i] = CAPTION_TIME.sub(lambda match: stretch_caption_time(match, speed), line)
            cues += 1
    if not cues:
        raise ValueError(f'No cues in {path}')
    with TemporaryDirectory(dir=path.parent, prefix=f'.{path.stem}-') as temp:
        staged = Path(temp) / path.name
        staged.write_bytes('\n'.join(lines).encode('utf-8'))
        path.replace(path.with_name(f'{path.stem}{TOO_LONG_SUFFIX}{path.suffix}'))
        staged.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--videos', type=Path, default=OUT_DIR, help='Video directory')
    parser.add_argument('--captions', type=Path, default=CAPTIONS_OUT_DIR, help='Captions directory')
    args = parser.parse_args()

    files = sorted(path for path in args.videos.iterdir() if path.is_file())
    failures = 0
    # Move too-long downloads aside first, so "{uid}.*" never names one.
    for path in files:
        if path.stem.endswith(TOO_LONG_SUFFIX):
            continue
        try:
            duration = probe_duration(path)
        except (subprocess.CalledProcessError, KeyError, ValueError) as exc:
            print(f'Failed to probe {path.name}: {exc}')
            failures += 1
            continue
        if duration >= TOO_LONG:
            path.replace(path.with_name(f'{path.stem}{TOO_LONG_SUFFIX}{path.suffix}'))

    # Stretch every too-long original lacking a published "{uid}.*" (also
    # resumes after an interrupted run).
    for path in sorted(args.videos.glob(f'*{TOO_LONG_SUFFIX}.*')):
        uid = path.stem.removesuffix(TOO_LONG_SUFFIX)
        if any(p.stem == uid and p.is_file() for p in args.videos.glob(f'{uid}.*')):
            continue
        try:
            duration = probe_duration(path)
            speed = duration / TARGET_DURATION
            print(f'Stretching {uid}: {duration:.1f}s x{speed:.3f}')
            stretch(path, args.videos / f'{uid}.mp4', speed)
            for captions in sorted(args.captions.glob(f'{uid}.*')):
                if captions.stem == uid and captions.is_file():
                    stretch_captions(captions, speed)
        except (subprocess.CalledProcessError, KeyError, ValueError) as exc:
            print(f'Failed to stretch {path.name}: {exc}')
            failures += 1
    return 1 if failures else 0


if __name__ == '__main__':
    raise SystemExit(main())
