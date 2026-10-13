"""
Replay the announcement bot's tape over events.csv and write event boundaries (actual start/end,
conference-local) to a txt file, to split the video recordings.

Pipeline:
1. `uv run python -m scripts.event_boundaries`  -> tmp/event_boundaries.txt
2. A human checks and edits the txt against the recordings (fill in the `recording` lines).
3. `uv run python -m scripts.event_boundaries_to_ffmpeg tmp/event_boundaries.txt`

Actual start: the frozen start if the bot pinned it, otherwise base start + the offset last in
effect on that day. End: base end shifted by the same amount (or the next event's start if
end_time is empty).
"""

from __future__ import annotations

import argparse
import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from zoneinfo import ZoneInfo

from long_running_bots.announcement_bot import STATE_DIR, parse_event_start_datetime
from utils.shared import load_conference_timezone_name

TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
SEPARATOR = " | "


def load_tape(path: Path) -> list[dict]:
    if not path.exists():
        print(f"Warning: no tape at {path}; using the base schedule.")
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def actual_start(uid: int, base: datetime, tape: list[dict]) -> datetime:
    start = base
    for record in tape:
        frozen = record["started"].get(str(uid))
        if frozen is not None:
            start = datetime.fromisoformat(frozen)
            continue
        if datetime.fromisoformat(record["at"]).astimezone(base.tzinfo).date() != base.date():
            continue
        offset = record["offset"]
        minutes = offset["minutes"] if offset and date.fromisoformat(offset["day"]) == base.date() else 0
        start = base + timedelta(minutes=minutes)
    return start.astimezone(base.tzinfo)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--sitedata", default="sitedata")
    parser.add_argument("--tape", type=Path, default=STATE_DIR / "announcement_bot_state.tape.jsonl")
    parser.add_argument("--out", type=Path, default=STATE_DIR / "event_boundaries.txt")
    args = parser.parse_args()

    timezone = ZoneInfo(load_conference_timezone_name(args.sitedata))
    tape = load_tape(args.tape)
    rows = pd.read_csv(Path(args.sitedata) / "events.csv").fillna("")

    events = []
    for _, row in rows.iterrows():
        start_date, start_time = str(row["start_date"]).strip(), str(row["start_time"]).strip()
        if not start_date or not start_time:
            continue
        uid = int(float(row["uid"]))
        base = parse_event_start_datetime(start_date, start_time, timezone)
        start = actual_start(uid, base, tape)
        end_time = str(row["end_time"]).strip()
        end = None
        if end_time:
            end = parse_event_start_datetime(start_date, end_time, timezone) + (start - base)
        events.append([start, end, uid, str(row["title"]).strip()])
    events.sort(key=lambda event: event[0])
    for event, following in zip(events, events[1:] + [None]):
        if event[1] is None:
            event[1] = following[0] if following else event[0]

    lines = [
        "# Event boundaries, conference-local. Check against the recordings and edit freely.",
        "# Event line:      START | END | UID | TITLE",
        "# Recording line:  recording | WALL-CLOCK START OF THE FILE | PATH",
        "#   Events below a recording line are cut from that file. Delete events you don't want cut.",
    ]
    day = None
    for start, end, uid, title in events:
        if start.date() != day:
            day = start.date()
            lines += ["", f"recording{SEPARATOR}{start.strftime(TIME_FORMAT)}{SEPARATOR}FILL_ME_{day.isoformat()}.mp4"]
        lines.append(SEPARATOR.join([start.strftime(TIME_FORMAT), end.strftime(TIME_FORMAT), str(uid), title]))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n")
    print(f"Wrote {len(events)} events to {args.out}.")


if __name__ == "__main__":
    main()
