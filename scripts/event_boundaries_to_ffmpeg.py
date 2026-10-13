"""
Read the (human-checked) txt from scripts/event_boundaries.py and print ffmpeg commands that cut
each event out of its recording. Output files are named `{date} {title}.{ext}`.

Example: `uv run python -m scripts.event_boundaries_to_ffmpeg tmp/event_boundaries.txt > cut.sh`
"""

from __future__ import annotations

import argparse
import re
import shlex
from datetime import datetime
from pathlib import Path

from scripts.event_boundaries import SEPARATOR, TIME_FORMAT


def safe_filename(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "-", text).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("boundaries", type=Path)
    parser.add_argument("--out-dir", type=Path, default=Path("tmp/event_videos"))
    parser.add_argument("--reencode", action="store_true", help="Frame-accurate cuts instead of `-c copy` (keyframe-aligned).")
    args = parser.parse_args()

    print("set -e")
    print(f"mkdir -p {shlex.quote(str(args.out_dir))}")
    recording: tuple[datetime, str] | None = None
    for number, line in enumerate(args.boundaries.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = [field.strip() for field in line.split(SEPARATOR.strip())]
        if fields[0] == "recording":
            recording = (datetime.strptime(fields[1], TIME_FORMAT), fields[2])
            continue
        assert len(fields) >= 4, f"Line {number}: expected START | END | UID | TITLE."
        assert recording is not None, f"Line {number}: no `recording` line above this event."
        start, end = (datetime.strptime(field, TIME_FORMAT) for field in fields[:2])
        title = SEPARATOR.strip().join(fields[3:])
        recording_start, path = recording
        seek = (start - recording_start).total_seconds()
        duration = (end - start).total_seconds()
        assert seek >= 0, f"Line {number}: event starts before its recording."
        assert duration > 0, f"Line {number}: end is not after start."
        out = args.out_dir / f"{start.date().isoformat()} {safe_filename(title)}{Path(path).suffix or '.mp4'}"
        codec = [] if args.reencode else ["-c", "copy"]
        command = ["ffmpeg", "-n", "-ss", f"{seek:.3f}", "-i", path, "-t", f"{duration:.3f}", *codec, str(out)]
        print(shlex.join(command))


if __name__ == "__main__":
    main()
