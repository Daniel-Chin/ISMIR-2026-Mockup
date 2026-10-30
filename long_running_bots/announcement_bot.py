'''
- Posts automatically on slack #announcements when a session starts.
    - Also posts the event channel description for visibility.
- Needs to be kept running throughout the conference.
- You need to create a bot:
    - https://api.slack.com/apps?new_app=1
    - New blank app.
    - App name "Announcement Bot".
    - Bot Token Scopes:
        - channels:read channels:join chat:write channels:history groups:history mpim:history im:history
    - Install App to Workspace.
    - Copy the **Bot User OAuth Token** (`xoxb-...`).
    - Paste in `.env`:
    - "SLACK_TOKEN_ANNOUNCEMENT_BOT=xoxb-..."
    - Set a profile image.
- You need to create a public channel #bot-home. Every exception is sent there.
  The bot joins it by itself.

Example CLI:
    - `uv run --env-file mockup.env python -m long_running_bots.announcement_bot --mockup`
    - `uv run --env-file mockup.env python -m long_running_bots.announcement_bot --mockup --testing`
    - `uv run --env-file   real.env python -m long_running_bots.announcement_bot`

Details:
- Interactive shell. Type `help` for commands. Bot output is printed above the prompt.
- Event IDs (`{e}`) are the `uid` column of events.csv.
- Announces each event `ANNOUNCE_IN_ADVANCE` minutes before its *adjusted* start
  (base schedule + today's offset).
- Schedule offset:
    - Set by the operator via `running late|early by {m}`, `calibrate {e} to {hh:mm}`, `goto {e}`.
    - Tagged with the conference-local date it applies to; only events on that date are shifted.
      A stale offset (from an earlier day) is cleared on load and on day change.
    - On change, posts "We are running XX minutes late." plus corrections for events that
      were already announced but have not started yet.
    - If running late, also posts an extra announcement at the *base* announcement time,
      for participants who missed the delay notice.
    - A due announcement is skipped if the event was already announced (any kind) no more than
      `2 * ANNOUNCE_IN_ADVANCE` before its adjusted start.
    - An event is frozen (its start pinned) `STARTED_GRACE` after its adjusted start, or when a
      later event is calibrated. Offset changes do not move frozen events.
- The event channel description (purpose) is posted into the event's channel once per event,
  at T - ANNOUNCE_IN_ADVANCE (adjusted), independent of which #general announcement goes out.
- Local state (offset, announcement log incl. purpose posts, frozen events) persists in `tmp/` (gitignored).
  90% of the time the bot stays on one machine. If the state file is missing, falls back to
  Slack history: match the last message containing `KEYWORD` to seek the event sequence.
- On startup, if an unannounced event started >=1m ago (and is not frozen), asks on the shell
  whether to announce it late. If no response in 1 minute, assume skip.
- Mockup (`--mockup`): the current event is assumed to run late until the operator types
  `goto next`. Events after the current one are never announced by the clock; extra
  announcements and offset messages only follow operator-set offsets.
- Testing (`--testing`): fake wall time = real wall time + an offset, initialized so that the
  first event starts in ANNOUNCE_IN_ADVANCE minutes. `+{m}` fast-forwards it. Uses its own state
  file, wiped on startup, and does not recover from Slack history.
    - Never touches Slack: messages are printed to stdout in an ASCII frame instead.
    - As a safety net, refuses to start if `SLACK_TOKEN_ANNOUNCEMENT_BOT` is set
      (in the environment or `.env`).
- Tape: every change to the offset or the frozen starts is appended to
  `tmp/announcement_bot_state*.tape.jsonl` (never rewritten). Keeping the bot's time correct
  (`goto`, `calibrate`, `running late`) therefore also serves to auto split the video recordings:
  `scripts/event_boundaries.py` replays the tape into event boundaries, which a human checks, then
  `scripts/event_boundaries_to_ffmpeg.py` turns into cut commands.
- Posts "I awake!" and "I exit." to #bot-home.
- Exceptions: recovered from where possible and sent to #bot-home right away. Repeats of the same
  error are only printed for `REPEAT_REPORT_INTERVAL_SECONDS`. If sending to #bot-home fails, the
  report is printed, stored, and printed again on exit.
    - Slack setup and history recovery at startup retry until they succeed.
    - A failing event does not block the others. Its post is retried on the next tick.
    - A failed offset message is rebuilt and retried on the next tick.
- Loads events.csv once at startup. If you change it during the conference, restart this script.
'''

from __future__ import annotations

import argparse
import importlib
import json
import os
import re
import sys
import textwrap
import threading
import time
import traceback
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from collections.abc import Callable
from typing import Any

import pandas as pd
from dotenv import load_dotenv
from zoneinfo import ZoneInfo

from catalogue.build_catalogue import slack_channel_id
from utils.deployment import check_deployment
from utils.shared import load_conference_timezone_name

ANNOUNCE_IN_ADVANCE = 10  # minutes
FRESH_WINDOW = timedelta(minutes=2 * ANNOUNCE_IN_ADVANCE)
STARTED_GRACE = timedelta(minutes=2 * ANNOUNCE_IN_ADVANCE)
ANNOUNCEMENTS_CHANNEL = "general"
BOT_HOME_CHANNEL = "bot-home"
KEYWORD = "Beep Bop"
PROMPT_TIMEOUT_SECONDS = 60
BOT_TOKEN_ENV_VAR = "SLACK_TOKEN_ANNOUNCEMENT_BOT"
MISSED_EVENT_THRESHOLD_SECONDS = 60
HISTORY_PAGE_LIMIT = 200
MAX_SLEEP_SECONDS = 30.0
STATE_DIR = Path("tmp")
REPEAT_REPORT_INTERVAL_SECONDS = 600
MAX_REPORT_CHARS = 3000

# Kinds of announcement log entries.
MAIN = "main"      # regular announcement at T - ANNOUNCE_IN_ADVANCE
EXTRA = "extra"    # announcement at the base-schedule time while running late
UPDATE = "update"  # correction appended to an offset message
SKIP = "skip"      # operator (or timeout) skipped a stale announcement
PURPOSE = "purpose"  # event channel description posted in the event's own channel
ANNOUNCING_KINDS = {MAIN, EXTRA, UPDATE}

HELP_TEXT = f'''Commands ({{e}} is the event uid from events.csv):
  whats {{e}}                       Show an event: base/adjusted start, status, announcements.
  whats next                      Show the next event.
  running late|early by {{m}}       Set today's offset to m minutes w.r.t. the base schedule.
  calibrate {{e}} to {{hhmm|hh:mm}}   Set the offset so that event e starts at that conf-local time.
                                  If the time looks 12h early, asks to confirm (`y`/`n`).
  goto {{e}}                        Same as `calibrate {{e}} to now`. `goto next` only in mockup.
  status                          Show offset, current/next events, and upcoming announcements.
  announce | skip                 Answer a pending stale-announcement question.
  +{{m}}                            (--testing only) Fast-forward the fake wall time by m minutes.
  help                            Show this help.
  Ctrl-D                          Quit.
Announcements go out {ANNOUNCE_IN_ADVANCE} min before the adjusted start.'''


@dataclass(frozen=True)
class ScheduledEvent:
    uid: int
    title: str
    channel_id: str
    start_at: datetime


@dataclass(frozen=True)
class AnnouncementPointer:
    channel_id: str
    posted_at: datetime


@dataclass(frozen=True)
class Offset:
    day: date
    minutes: int
    updated_at: datetime


@dataclass(frozen=True)
class LogEntry:
    uid: int
    kind: str
    at: datetime


@dataclass
class BotState:
    offset: Offset | None = None
    log: list[LogEntry] = field(default_factory=list)
    started: dict[int, datetime] = field(default_factory=dict)  # frozen event starts
    mock_cursor_uid: int | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "offset": None if self.offset is None else {
                "day": self.offset.day.isoformat(),
                "minutes": self.offset.minutes,
                "updated_at": self.offset.updated_at.isoformat(),
            },
            "log": [
                {"uid": entry.uid, "kind": entry.kind, "at": entry.at.isoformat()}
                for entry in self.log
            ],
            "started": {str(uid): at.isoformat() for uid, at in self.started.items()},
            "mock_cursor_uid": self.mock_cursor_uid,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> BotState:
        offset_data = data.get("offset")
        return cls(
            offset=None if offset_data is None else Offset(
                day=date.fromisoformat(offset_data["day"]),
                minutes=int(offset_data["minutes"]),
                updated_at=datetime.fromisoformat(offset_data["updated_at"]),
            ),
            log=[
                LogEntry(
                    uid=int(entry["uid"]),
                    kind=str(entry["kind"]),
                    at=datetime.fromisoformat(entry["at"]),
                )
                for entry in data.get("log", [])
            ],
            started={
                int(uid): datetime.fromisoformat(at)
                for uid, at in data.get("started", {}).items()
            },
            mock_cursor_uid=data.get("mock_cursor_uid"),
        )


@dataclass
class PendingPrompt:
    uids: list[int]
    deadline: datetime


def plural_minutes(n: int) -> str:
    return f"{n} minute" if n == 1 else f"{n} minutes"


def slack_clock(dt: datetime) -> str:
    # Rendered by Slack in each reader's local time; the fallback is conf-local.
    return f"<!date^{int(dt.timestamp())}^{{time}}|{dt.strftime('%H:%M %Z')}>"


def render_relative(t_minus: int) -> str:
    if t_minus > 0:
        return f"is starting in {plural_minutes(t_minus)}"
    if t_minus == 0:
        return "is starting now"
    return f"started {plural_minutes(-t_minus)} ago"


def render_announcement(channel_id: str, t_minus: int) -> str:
    return f"{KEYWORD}. Hello everyone! <#{channel_id}> {render_relative(t_minus)}."


def render_extra_announcement(
    channel_id: str, base_start: datetime, adjusted_start: datetime, t_minus: int,
) -> str:
    return (
        f"{KEYWORD}. Hi, everyone! <#{channel_id}> was planned for {slack_clock(base_start)} "
        f"but will now start at {slack_clock(adjusted_start)}, in {plural_minutes(t_minus)}."
    )


def render_offset_message(
    minutes: int, corrections: list[tuple[str, datetime, int]],
) -> str:
    if minutes > 0:
        sentences = [f"{KEYWORD}. We are running {plural_minutes(minutes)} late."]
    elif minutes < 0:
        sentences = [f"{KEYWORD}. We are running {plural_minutes(-minutes)} early."]
    else:
        sentences = [f"{KEYWORD}. We are back on schedule."]
    for channel_id, adjusted_start, t_minus in corrections:
        if t_minus == 0:
            sentences.append(f"<#{channel_id}> is starting now.")
        else:
            sentences.append(
                f"<#{channel_id}> now starts at {slack_clock(adjusted_start)}, "
                f"in {plural_minutes(t_minus)}."
            )
    return " ".join(sentences)


def get_event_channel_message(client: Any, channel_id: str) -> str:
    response = client.conversations_info(channel=channel_id)
    purpose = str(
        response.get("channel", {}).get("purpose", {}).get("value", "")
    ).strip()
    return purpose


def load_events(site_data_path: str) -> list[ScheduledEvent]:
    config_path = Path(site_data_path) / "config.yml"
    assert config_path.exists()
    timezone = ZoneInfo(load_conference_timezone_name(site_data_path))
    csv_path = Path(site_data_path) / "events.csv"
    csv_data = pd.read_csv(csv_path).fillna("")

    events: list[ScheduledEvent] = []
    for _, row in csv_data.iterrows():
        channel_id = slack_channel_id(str(row.get("channel_url", "")).strip())
        start_date = str(row.get("start_date", "")).strip()
        start_time = str(row.get("start_time", "")).strip()
        title = str(row.get("title", "")).strip()
        uid = str(row.get("uid", "")).strip()
        if not channel_id or not start_date or not start_time or not title or not uid:
            say(f"Not announcing uid={uid or '?'} \"{title}\": missing channel_url, date, time, or title.")
            continue

        start_at = parse_event_start_datetime(start_date, start_time, timezone)
        events.append(
            ScheduledEvent(
                uid=int(float(uid)),
                title=title,
                channel_id=channel_id,
                start_at=start_at,
            )
        )

    uids = [event.uid for event in events]
    assert len(uids) == len(set(uids)), f"Duplicate uid in {csv_path}."
    events.sort(key=lambda event: event.start_at)
    return events


def parse_event_start_datetime(
    start_date: str, start_time: str, timezone: ZoneInfo
) -> datetime:
    event_date = date.fromisoformat(start_date)
    time_parts = start_time.split(":")
    if len(time_parts) not in {2, 3}:
        raise ValueError(
            f"Invalid time '{start_time}'. Expected H:MM, HH:MM, H:MM:SS, or HH:MM:SS."
        )

    hour = int(time_parts[0])
    minute = int(time_parts[1])
    second = int(time_parts[2]) if len(time_parts) == 3 else 0
    event_time = dtime(hour=hour, minute=minute, second=second)
    return datetime.combine(event_date, event_time, tzinfo=timezone)


class StdoutSlackClient:
    """Stands in for slack_sdk.WebClient in --testing. Prints posts instead of sending them."""

    FRAME_WIDTH = 78

    def __init__(self, channel_names: dict[str, str]) -> None:
        self.channel_names = channel_names

    def readable(self, text: str) -> str:
        text = re.sub(r"<!date\^\d+\^\{time\}\|([^>]+)>", r"\1", text)
        return re.sub(
            r"<#([A-Za-z0-9]+)(?:\|[^>]*)?>",
            lambda m: "#" + self.channel_names.get(m.group(1), m.group(1)),
            text,
        )

    def chat_postMessage(self, channel: str, text: str) -> dict[str, Any]:
        inner = self.FRAME_WIDTH - 4
        title = f" Slack #{self.channel_names.get(channel, channel)} "
        lines = [
            wrapped
            for paragraph in self.readable(text).splitlines() or [""]
            for wrapped in (textwrap.wrap(paragraph, inner) or [""])
        ]
        frame = [f"+-{title}{'-' * (inner - len(title))}-+"]
        frame += [f"| {line.ljust(inner)} |" for line in lines]
        frame.append(f"+{'-' * (inner + 2)}+")
        print("\n".join(frame), flush=True)
        return {"ok": True}

    def conversations_info(self, channel: str) -> dict[str, Any]:
        name = self.channel_names.get(channel, channel)
        return {"channel": {"purpose": {"value": f"(channel purpose of #{name})"}}}

    def conversations_join(self, channel: str) -> dict[str, Any]:
        return {"ok": True}

    def conversations_history(self, **kwargs: Any) -> dict[str, Any]:
        return {"messages": []}


def create_slack_client(is_mockup: bool = False) -> Any:
    check_deployment(is_mockup)
    env_path = Path(".") / ".env"
    load_dotenv(dotenv_path=env_path)
    token = os.environ.get(BOT_TOKEN_ENV_VAR, "").strip()
    if not token:
        raise RuntimeError(
            f"Missing {BOT_TOKEN_ENV_VAR} in environment or .env file."
        )
    slack_sdk = importlib.import_module("slack_sdk")
    return slack_sdk.WebClient(token=token)


def find_channel_id(client: Any, channel_name: str) -> str:
    next_cursor: str | None = None
    while True:
        response = client.conversations_list(
            types="public_channel",
            limit=HISTORY_PAGE_LIMIT,
            cursor=next_cursor,
        )
        for channel in response.get("channels", []):
            if channel.get("name") == channel_name:
                return str(channel["id"])
        next_cursor = response.get("response_metadata", {}).get("next_cursor") or None
        if next_cursor is None:
            break
    raise RuntimeError(f"Could not find Slack channel '{channel_name}'.")


def join_channel_if_needed(client: Any, channel_id: str) -> None:
    try:
        client.conversations_join(channel=channel_id)
    except Exception as exc:
        error_response = getattr(exc, "response", {})
        error_code = error_response.get("error", "") if hasattr(error_response, "get") else ""
        if error_code not in {"method_not_supported_for_channel_type", "already_in_channel"}:
            raise


def extract_announcement_pointer(message: dict[str, Any]) -> AnnouncementPointer | None:
    text = str(message.get("text", ""))
    if KEYWORD not in text:
        return None

    match = re.search(
        r"Hello everyone!\s+<#([A-Za-z0-9]+)(?:\|[^>]+)?>\s+"
        r"(?:is starting in\s+-?\d+\s+minutes?|is starting now|started\s+\d+\s+minutes?\s+ago)\.",
        text,
    )
    if match is None:
        return None

    ts_text = str(message.get("ts", "")).strip()
    if not ts_text:
        return None

    return AnnouncementPointer(
        channel_id=match.group(1).strip(),
        posted_at=datetime.fromtimestamp(float(ts_text), tz=ZoneInfo("UTC")),
    )


def fetch_last_announcement(
    client: Any, channel_id: str
) -> AnnouncementPointer | None:
    next_cursor: str | None = None
    while True:
        response = client.conversations_history(
            channel=channel_id,
            limit=HISTORY_PAGE_LIMIT,
            cursor=next_cursor,
        )
        for message in response.get("messages", []):
            pointer = extract_announcement_pointer(message)
            if pointer is not None:
                return pointer
        next_cursor = response.get("response_metadata", {}).get("next_cursor") or None
        if next_cursor is None:
            return None


def find_resume_index(
    events: list[ScheduledEvent],
    last_announcement: AnnouncementPointer | None,
) -> int:
    if last_announcement is None:
        return 0

    matching_positions = [
        position
        for position, event in enumerate(events)
        if event.channel_id == last_announcement.channel_id
    ]
    if not matching_positions:
        return 0

    posted_at = last_announcement.posted_at.astimezone(events[0].start_at.tzinfo)
    best_position = min(
        matching_positions,
        key=lambda position: abs(
            (
                events[position].start_at - timedelta(minutes=ANNOUNCE_IN_ADVANCE)
                - posted_at
            ).total_seconds()
        ),
    )
    return best_position + 1


def minutes_between(start: datetime, end: datetime) -> int:
    return round((end - start).total_seconds() / 60)


def round_to_minute(dt: datetime) -> datetime:
    floored = dt.replace(second=0, microsecond=0)
    return floored + timedelta(minutes=1) if dt.second >= 30 else floored


stamp_clock: Callable[[], datetime] = datetime.now


def say(*lines: str) -> None:
    stamp = stamp_clock().strftime("%H:%M:%S")
    for line in lines:
        print(f"[{stamp}] {line}", flush=True)


class ErrorReporter:
    def __init__(self) -> None:
        self.client: Any = None
        self.channel_id: str | None = None
        self.last_sent: dict[str, float] = {}
        self.undelivered: list[str] = []

    def connect(self, client: Any, channel_id: str | None = None) -> None:
        self.client = client
        self.channel_id = channel_id

    def send(self, text: str) -> None:
        if self.client is None:
            raise RuntimeError("No Slack client yet.")
        if self.channel_id is None:
            channel_id = find_channel_id(self.client, BOT_HOME_CHANNEL)
            join_channel_if_needed(self.client, channel_id)
            self.channel_id = channel_id
        self.client.chat_postMessage(channel=self.channel_id, text=text)

    def report(self, context: str) -> None:
        """Call from an `except` block. Never raises."""
        trace = traceback.format_exc()
        print(trace, end="", file=sys.stderr, flush=True)
        say(f"!! Error while {context}.")
        key = f"{context}: {traceback.format_exc(limit=0)}"
        now = time.monotonic()
        last = self.last_sent.get(key)
        if last is not None and now - last < REPEAT_REPORT_INTERVAL_SECONDS:
            return
        self.last_sent[key] = now
        self.deliver(f"Error while {context}:\n```{trace[-MAX_REPORT_CHARS:]}```")

    def deliver(self, text: str) -> None:
        """Never raises."""
        try:
            self.send(text)
        except Exception:
            say(f"!! Could not send to #{BOT_HOME_CHANNEL}:", text)
            traceback.print_exc()
            self.undelivered.append(text)

    def print_undelivered(self) -> None:
        if self.undelivered:
            say(f"!! {len(self.undelivered)} error(s) never reached #{BOT_HOME_CHANNEL}:",
                *self.undelivered)


reporter = ErrorReporter()


def attempt(context: str, action: Callable[..., Any], *args: Any) -> bool:
    try:
        action(*args)
    except Exception:
        reporter.report(context)
        return False
    return True


def retry_until_success(context: str, action: Callable[..., Any], *args: Any) -> Any:
    while True:
        try:
            return action(*args)
        except Exception:
            reporter.report(context)
            time.sleep(MAX_SLEEP_SECONDS)


class AnnouncementBot:
    def __init__(
        self,
        events: list[ScheduledEvent],
        client: Any,
        announcements_channel_id: str,
        state_path: Path,
        is_mockup: bool,
        clock: Callable[[], datetime] | None = None,
        is_testing: bool = False,
    ) -> None:
        self.events = events
        self.by_uid = {event.uid: event for event in events}
        self.index_of = {event.uid: i for i, event in enumerate(events)}
        self.client = client
        self.announcements_channel_id = announcements_channel_id
        self.state_path = state_path
        self.is_mockup = is_mockup
        self.tz = events[0].start_at.tzinfo
        self.is_testing = is_testing
        self.fake_time_offset = timedelta(0)
        if is_testing:
            first_due = events[0].start_at - timedelta(minutes=ANNOUNCE_IN_ADVANCE)
            self.fake_time_offset = first_due - datetime.now(tz=self.tz)
        self._clock = clock or (lambda: datetime.now(tz=self.tz) + self.fake_time_offset)
        self.lock = threading.RLock()
        self.wakeup = threading.Condition(self.lock)
        self.pending: PendingPrompt | None = None
        # (event, as typed, typed + 12h) awaiting `y`/`n`.
        self.pending_calibration: tuple[ScheduledEvent, datetime, datetime] | None = None
        self.state = BotState()
        self.tape_path = state_path.with_suffix(".tape.jsonl")
        self.last_taped: dict[str, Any] | None = None
        self.offset_post_owed = False

    # ---------- time & schedule ----------

    def now(self) -> datetime:
        return self._clock().astimezone(self.tz)

    def today(self) -> date:
        return self.now().date()

    def offset_minutes(self, event: ScheduledEvent) -> int:
        offset = self.state.offset
        if offset is None or offset.day != event.start_at.date():
            return 0
        return offset.minutes

    def adjusted_start(self, event: ScheduledEvent) -> datetime:
        frozen = self.state.started.get(event.uid)
        if frozen is not None:
            return frozen
        return event.start_at + timedelta(minutes=self.offset_minutes(event))

    def is_frozen(self, event: ScheduledEvent) -> bool:
        return event.uid in self.state.started

    def cursor_index(self) -> int:
        uid = self.state.mock_cursor_uid
        return -1 if uid is None or uid not in self.index_of else self.index_of[uid]

    def is_held(self, event: ScheduledEvent) -> bool:
        # Mockup: the current event runs late until the operator says `goto`.
        return self.is_mockup and self.index_of[event.uid] > self.cursor_index()

    def entries_for(self, uid: int, kinds: set[str] | None = None) -> list[LogEntry]:
        return [
            entry for entry in self.state.log
            if entry.uid == uid and (kinds is None or entry.kind in kinds)
        ]

    def announced_since(self, event: ScheduledEvent, since: datetime) -> LogEntry | None:
        recent = [
            entry for entry in self.entries_for(event.uid)
            if entry.kind != PURPOSE and entry.at >= since
        ]
        return recent[-1] if recent else None

    def next_event(self) -> ScheduledEvent | None:
        if self.is_mockup:
            index = self.cursor_index() + 1
            return self.events[index] if index < len(self.events) else None
        now = self.now()
        for event in self.events:
            if not self.is_frozen(event) and self.adjusted_start(event) > now:
                return event
        return None

    def main_due(self, event: ScheduledEvent, now: datetime) -> bool:
        if self.is_frozen(event) or self.is_held(event):
            return False
        start = self.adjusted_start(event)
        if now < start - timedelta(minutes=ANNOUNCE_IN_ADVANCE):
            return False
        return self.announced_since(event, start - FRESH_WINDOW) is None

    def purpose_due(self, event: ScheduledEvent, now: datetime) -> bool:
        # Once per event, at T - ANNOUNCE_IN_ADVANCE, whichever #general message (if any) went out.
        if self.is_frozen(event) or self.is_held(event):
            return False
        if now < self.adjusted_start(event) - timedelta(minutes=ANNOUNCE_IN_ADVANCE):
            return False
        return not self.entries_for(event.uid, {PURPOSE, SKIP})

    def extra_due(self, event: ScheduledEvent, now: datetime) -> bool:
        late = self.offset_minutes(event)
        if late <= 0 or self.is_frozen(event):
            return False
        base_due = event.start_at - timedelta(minutes=ANNOUNCE_IN_ADVANCE)
        if not (base_due <= now < event.start_at):
            return False
        if self.adjusted_start(event) <= now:
            return False
        return self.announced_since(event, event.start_at - FRESH_WINDOW) is None

    # ---------- persistence ----------

    def save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.state_path.with_suffix(".json.tmp")
        tmp_path.write_text(json.dumps(self.state.to_json(), indent=2))
        tmp_path.replace(self.state_path)
        self.append_tape()

    def append_tape(self) -> None:
        snapshot = {key: self.state.to_json()[key] for key in ("offset", "started")}
        if snapshot == self.last_taped:
            return
        self.last_taped = snapshot
        with self.tape_path.open("a") as f:
            f.write(json.dumps({"at": self.now().isoformat(), **snapshot}) + "\n")

    def load_or_recover(self) -> None:
        if self.is_testing:
            say(f"Testing: starting from a fresh state at {self.state_path}.")
            self.tape_path.unlink(missing_ok=True)
            self.save()
            return
        if self.state_path.exists():
            try:
                self.state = BotState.from_json(json.loads(self.state_path.read_text()))
                say(f"Loaded state from {self.state_path} "
                    f"({len(self.state.log)} logged announcements, "
                    f"{len(self.state.started)} frozen events).")
                return
            except Exception as exc:
                say(f"!! Could not parse {self.state_path} ({exc!r}); recovering from Slack history.")
        else:
            say(f"No state file at {self.state_path}; recovering from Slack history.")
        retry_until_success("recovering from Slack history", self.recover_from_slack)
        self.save()

    def recover_from_slack(self) -> None:
        pointer = fetch_last_announcement(self.client, self.announcements_channel_id)
        resume = find_resume_index(self.events, pointer)
        if pointer is None or resume == 0:
            say("No previous announcement found in Slack; starting from the first event.")
        else:
            last = self.events[resume - 1]
            for event in self.events[:resume - 1]:
                self.state.started[event.uid] = event.start_at
            posted_at = pointer.posted_at.astimezone(self.tz)
            self.state.log.append(LogEntry(uid=last.uid, kind=MAIN, at=posted_at))
            self.state.log.append(LogEntry(uid=last.uid, kind=PURPOSE, at=posted_at))
            say(f"Last announcement in Slack was for {self.describe(last)}.")
        if self.is_mockup:
            before_today = [
                i for i, event in enumerate(self.events) if event.start_at.date() < self.today()
            ]
            index = max([resume - 1, *before_today], default=-1)
            self.state.mock_cursor_uid = self.events[index].uid if index >= 0 else None

    # ---------- formatting ----------

    def describe(self, event: ScheduledEvent) -> str:
        base = event.start_at.strftime("%H:%M")
        adjusted = self.adjusted_start(event)
        day = event.start_at.strftime("%a %m-%d")
        if adjusted == event.start_at:
            times = f"{day} {base}"
        else:
            times = f"{day} {base} -> {adjusted.strftime('%H:%M')}"
        return f"#{event.uid} \"{event.title}\" ({times})"

    def describe_offset(self) -> str:
        offset = self.state.offset
        if offset is None or offset.minutes == 0:
            text = "on schedule (offset 0)"
        elif offset.minutes > 0:
            text = f"running {plural_minutes(offset.minutes)} LATE"
        else:
            text = f"running {plural_minutes(-offset.minutes)} EARLY"
        if offset is not None:
            text += (f", for {offset.day.isoformat()}, "
                     f"set at {offset.updated_at.astimezone(self.tz).strftime('%m-%d %H:%M')}")
        return text

    def event_status_lines(self, event: ScheduledEvent) -> list[str]:
        now = self.now()
        start = self.adjusted_start(event)
        lines = [self.describe(event)]
        if self.is_frozen(event):
            lines.append(f"  frozen: started at {start.strftime('%H:%M')}")
        elif self.is_held(event):
            lines.append("  held: mockup waits for `goto` before announcing")
        else:
            due = start - timedelta(minutes=ANNOUNCE_IN_ADVANCE)
            fresh = self.announced_since(event, start - FRESH_WINDOW)
            if fresh is not None:
                verb = "skipped" if fresh.kind == SKIP else f"already announced ({fresh.kind})"
                lines.append(f"  main: not needed, {verb} "
                             f"at {fresh.at.astimezone(self.tz).strftime('%H:%M')}")
            elif due > now:
                lines.append(f"  main: due at {due.strftime('%H:%M')} "
                             f"(in {plural_minutes(minutes_between(now, due))})")
            else:
                lines.append("  main: due now")
        purpose = self.entries_for(event.uid, {PURPOSE})
        if purpose:
            lines.append(f"  purpose: posted at {purpose[-1].at.astimezone(self.tz).strftime('%H:%M')}")
        elif not self.is_frozen(event) and not self.is_held(event):
            due = start - timedelta(minutes=ANNOUNCE_IN_ADVANCE)
            lines.append(f"  purpose: due at {due.strftime('%H:%M')}" if due > now else "  purpose: due now")
        late = self.offset_minutes(event)
        base_due = event.start_at - timedelta(minutes=ANNOUNCE_IN_ADVANCE)
        if late > 0 and not self.is_frozen(event) and now < event.start_at:
            if self.announced_since(event, event.start_at - FRESH_WINDOW) is not None:
                lines.append("  extra: not needed, already announced")
            else:
                lines.append(f"  extra (running late): due at {base_due.strftime('%H:%M')}")
        for entry in self.entries_for(event.uid):
            lines.append(f"  log: {entry.kind} at {entry.at.astimezone(self.tz).strftime('%m-%d %H:%M')}")
        return lines

    def print_status(self) -> None:
        now = self.now()
        lines = [
            f"=== {'MOCKUP' if self.is_mockup else 'LIVE'}{' | TESTING (fake time)' if self.is_testing else ''} | now {now.strftime('%a %Y-%m-%d %H:%M:%S %Z')} ===",
            f"Offset: {self.describe_offset()}",
        ]
        if self.is_mockup:
            cursor = self.cursor_index()
            current = self.events[cursor] if cursor >= 0 else None
            lines.append(f"Current (mockup): {self.describe(current) if current else 'none yet'}")
        upcoming = [
            event for event in self.events
            if not self.is_frozen(event) and self.adjusted_start(event) + STARTED_GRACE > now
        ][:3]
        lines.append("Upcoming:" if upcoming else "Upcoming: none")
        for event in upcoming:
            lines.extend("  " + line for line in self.event_status_lines(event))
        if self.pending is not None:
            lines.append("!! Pending question: `announce` or `skip` (see above).")
        say(*lines)

    # ---------- posting ----------

    def post(self, text: str) -> None:
        self.client.chat_postMessage(channel=self.announcements_channel_id, text=text)

    def post_purpose(self, event: ScheduledEvent, now: datetime) -> None:
        desc = get_event_channel_message(self.client, event.channel_id)
        if desc:
            join_channel_if_needed(self.client, event.channel_id)
            message = desc.lstrip('_\n')
            self.client.chat_postMessage(channel=event.channel_id, text=message)
            say(f"Posted event channel purpose for {event.title} to <#{event.channel_id}>.")
        else:
            say(f"No purpose text configured for {event.title}; skipping event-channel post.")
        # Logged either way, so an empty purpose is not retried every tick.
        self.state.log.append(LogEntry(uid=event.uid, kind=PURPOSE, at=now))
        self.save()

    def post_main(self, event: ScheduledEvent, now: datetime) -> None:
        t_minus = minutes_between(now, self.adjusted_start(event))
        self.post(render_announcement(event.channel_id, t_minus))
        self.state.log.append(LogEntry(uid=event.uid, kind=MAIN, at=now))
        self.save()
        say(f">> Announced {self.describe(event)}: {render_relative(t_minus)}.")

    def post_extra(self, event: ScheduledEvent, now: datetime) -> None:
        start = self.adjusted_start(event)
        late = self.offset_minutes(event)
        t_minus = minutes_between(now, start)
        self.post(render_extra_announcement(event.channel_id, event.start_at, start, t_minus))
        self.state.log.append(LogEntry(uid=event.uid, kind=EXTRA, at=now))
        self.save()
        say(f">> Extra (running {plural_minutes(late)} late) announcement for "
            f"{self.describe(event)}, at its base-schedule time.")

    # ---------- scheduler ----------

    def freeze_started(self, now: datetime) -> None:
        for event in self.events:
            if self.is_frozen(event) or self.is_held(event):
                continue
            start = self.adjusted_start(event)
            if now >= start + STARTED_GRACE:
                self.state.started[event.uid] = start

    def clear_stale_offset(self, now: datetime) -> None:
        offset = self.state.offset
        if offset is not None and offset.day < now.date():
            say(f"Day changed: clearing offset from {offset.day.isoformat()} "
                f"({offset.minutes:+d} min). Back to the base schedule.")
            self.state.offset = None
            self.save()

    def find_stale(self, now: datetime) -> list[ScheduledEvent]:
        threshold = timedelta(seconds=MISSED_EVENT_THRESHOLD_SECONDS)
        return [
            event for event in self.events
            if self.main_due(event, now) and now - self.adjusted_start(event) >= threshold
        ]

    def ask_about_stale(self, stale: list[ScheduledEvent]) -> None:
        now = self.now()
        self.pending = PendingPrompt(
            uids=[event.uid for event in stale],
            deadline=now + timedelta(seconds=PROMPT_TIMEOUT_SECONDS),
        )
        lines = ["!! Missed announcement(s) while the bot was down:"]
        for event in stale:
            t_minus = minutes_between(now, self.adjusted_start(event))
            lines.append(f"   {self.describe(event)}: {render_relative(t_minus)}")
        lines.append(f"!! Type `announce` to post late, or `skip`. "
                     f"Auto-skip in {PROMPT_TIMEOUT_SECONDS}s.")
        say(*lines)

    def resolve_pending(self, announce: bool) -> None:
        pending = self.pending
        assert pending is not None
        self.pending = None
        now = self.now()
        for uid in pending.uids:
            attempt(f"resolving stale event #{uid}", self.resolve_stale_event, uid, announce, now)
        self.save()

    def resolve_stale_event(self, uid: int, announce: bool, now: datetime) -> None:
        event = self.by_uid[uid]
        if announce and self.main_due(event, now):
            self.post_main(event, now)
            if self.purpose_due(event, now):
                self.post_purpose(event, now)
        else:
            self.state.log.append(LogEntry(uid=uid, kind=SKIP, at=now))
            say(f"Skipped stale announcement for {self.describe(event)}.")

    def tick(self) -> float:
        with self.lock:
            now = self.now()
            attempt("clearing a stale offset", self.clear_stale_offset, now)
            attempt("freezing started events", self.freeze_started, now)
            if self.pending is not None and now >= self.pending.deadline:
                say("No response received; skipping.")
                attempt("skipping stale events", self.resolve_pending, False)
            if self.offset_post_owed:
                attempt("retrying the schedule update", self.post_offset_update)
            pending_uids = set(self.pending.uids) if self.pending else set()
            for event in self.events:
                if event.uid in pending_uids:
                    continue
                attempt(f"announcing event #{event.uid}", self.post_due, event, now)
            attempt("saving state", self.save)
            return self.seconds_until_next_action(now)

    def post_due(self, event: ScheduledEvent, now: datetime) -> None:
        if self.extra_due(event, now):
            self.post_extra(event, now)
        if self.main_due(event, now):
            self.post_main(event, now)
        if self.purpose_due(event, now):
            self.post_purpose(event, now)

    def seconds_until_next_action(self, now: datetime) -> float:
        candidates: list[datetime] = []
        for event in self.events:
            if self.is_frozen(event):
                continue
            start = self.adjusted_start(event)
            candidates.append(event.start_at - timedelta(minutes=ANNOUNCE_IN_ADVANCE))
            if not self.is_held(event):
                candidates.append(start - timedelta(minutes=ANNOUNCE_IN_ADVANCE))
                candidates.append(start + STARTED_GRACE)
        if self.pending is not None:
            candidates.append(self.pending.deadline)
        future = [(c - now).total_seconds() for c in candidates if c > now]
        return max(0.5, min([MAX_SLEEP_SECONDS, *future]))

    def scheduler_loop(self) -> None:
        while True:
            try:
                wait = self.tick()
            except Exception:
                reporter.report("running the scheduler (will retry)")
                wait = MAX_SLEEP_SECONDS
            with self.wakeup:
                self.wakeup.wait(timeout=wait)

    def poke(self) -> None:
        with self.wakeup:
            self.wakeup.notify_all()

    # ---------- offset changes ----------

    def apply_offset(self, minutes: int, day: date) -> None:
        now = self.now()
        old = self.state.offset
        old_minutes = old.minutes if old is not None and old.day == day else 0
        self.state.offset = Offset(day=day, minutes=minutes, updated_at=now)
        self.save()
        if minutes == old_minutes:
            say(f"Offset unchanged ({minutes:+d} min); nothing posted.")
            return
        self.offset_post_owed = True
        if not attempt("posting the schedule update", self.post_offset_update):
            say("!! Offset saved locally; the schedule update will be retried.")

    def post_offset_update(self) -> None:
        offset = self.state.offset
        if offset is None:
            self.offset_post_owed = False
            return
        now = self.now()
        corrections: list[tuple[str, datetime, int]] = []
        corrected: list[ScheduledEvent] = []
        for event in self.events:
            if self.is_frozen(event) or not self.entries_for(event.uid, ANNOUNCING_KINDS):
                continue
            start = self.adjusted_start(event)
            t_minus = minutes_between(now, start)
            if t_minus >= 0:
                corrections.append((event.channel_id, start, t_minus))
                corrected.append(event)
        text = render_offset_message(offset.minutes, corrections)
        self.post(text)
        self.offset_post_owed = False
        for event in corrected:
            self.state.log.append(LogEntry(uid=event.uid, kind=UPDATE, at=now))
        self.save()
        if self.is_testing:
            say(">> Posted schedule update.")
        else:
            say(">> Posted schedule update:", *("   " + line for line in text.splitlines()))

    def calibrate(self, event: ScheduledEvent, target: datetime) -> bool:
        if event.start_at.date() != self.today():
            say(f"Rejected: {self.describe(event)} is not today ({self.today().isoformat()}).")
            return False
        now = self.now()
        index = self.index_of[event.uid]
        for earlier in self.events[:index]:
            if not self.is_frozen(earlier):
                self.state.started[earlier.uid] = min(self.adjusted_start(earlier), now)
        for later in self.events[index:]:
            self.state.started.pop(later.uid, None)
        minutes = minutes_between(event.start_at, target)
        self.apply_offset(minutes, event.start_at.date())
        return True

    # ---------- commands ----------

    def resolve_event(self, token: str) -> ScheduledEvent | None:
        if token == "next":
            event = self.next_event()
            if event is None:
                say("No next event.")
            return event
        event = self.by_uid.get(int(token))
        if event is None:
            say(f"No event with uid {token}.")
        return event

    def handle_command(self, line: str) -> None:
        line = line.strip().lower()
        if not line:
            return
        with self.lock:
            try:
                self._dispatch(line)
            except Exception:
                reporter.report(f"running command {line!r}")
            self.poke()

    def _dispatch(self, line: str) -> None:
        if line in {"help", "?"}:
            say(*HELP_TEXT.splitlines())
            return
        if line == "status":
            self.print_status()
            return
        if self.pending_calibration is not None:
            event, typed, plus_12h = self.pending_calibration
            self.pending_calibration = None
            if line in {"y", "yes"}:
                self.run_calibration(event, plus_12h)
                return
            if line in {"n", "no"}:
                self.run_calibration(event, typed)
                return
            say(f"Calibration of #{event.uid} cancelled.")
        if line in {"y", "n", "yes", "no"}:
            say("Nothing to confirm.")
            return
        if line in {"announce", "skip"}:
            if self.pending is None:
                say("Nothing pending.")
                return
            self.resolve_pending(announce=line == "announce")
            self.print_status()
            return

        match = re.fullmatch(r"\+\s*(\d+)", line)
        if match:
            if not self.is_testing:
                say("Rejected: `+{m}` is only allowed with --testing.")
                return
            self.fast_forward(timedelta(minutes=int(match.group(1))))
            self.print_status()
            return

        match = re.fullmatch(r"whats\s+(\d+|next)", line)
        if match:
            event = self.resolve_event(match.group(1))
            if event is not None:
                say(*self.event_status_lines(event))
            return

        match = re.fullmatch(r"running\s+(late|early)\s+by\s+(\d+)(?:\s*(?:m|min|mins|minutes?))?", line)
        if match:
            minutes = int(match.group(2)) * (1 if match.group(1) == "late" else -1)
            today = self.today()
            if not any(event.start_at.date() == today for event in self.events):
                say(f"Warning: no events on {today.isoformat()}; the offset affects nothing.")
            self.freeze_started(self.now())
            self.apply_offset(minutes, today)
            self.print_status()
            return

        match = re.fullmatch(r"calibrate\s+(\S+)\s+to\s+(?:(\d{1,2}):(\d{2})|(\d{3,4}))", line)
        if match:
            if match.group(1) == "next":
                say("Rejected: `calibrate next` is ambiguous. Use the uid (see `whats next`).")
                return
            if not match.group(1).isdigit():
                say(f"Bad event id: {match.group(1)}")
                return
            if match.group(4):
                hour, minute = divmod(int(match.group(4)), 100)
            else:
                hour, minute = int(match.group(2)), int(match.group(3))
            if hour > 23 or minute > 59:
                say(f"Bad time: {hour}:{minute:02d}")
                return
            event = self.resolve_event(match.group(1))
            if event is None:
                return
            target = datetime.combine(event.start_at.date(), dtime(hour, minute), tzinfo=self.tz)
            plus_12h = target + timedelta(hours=12)
            if hour < 12 and abs(plus_12h - event.start_at) < abs(target - event.start_at):
                self.pending_calibration = (event, target, plus_12h)
                say(f"?? {target.strftime('%H:%M')} is {abs(minutes_between(event.start_at, target))} min "
                    f"from the base start of {self.describe(event)}. "
                    f"Did you mean {plus_12h.strftime('%H:%M')}?",
                    f"?? `y` = {plus_12h.strftime('%H:%M')}, `n` = {target.strftime('%H:%M')} as typed. "
                    "Any other command except `status`/`help` cancels.")
                return
            self.run_calibration(event, target)
            return

        match = re.fullmatch(r"goto\s+(\d+|next)", line)
        if match:
            if match.group(1) == "next" and not self.is_mockup:
                say("Rejected: `goto next` is only allowed in mockup. Use the uid (see `whats next`).")
                return
            event = self.resolve_event(match.group(1))
            if event is None:
                return
            target = round_to_minute(self.now())
            say(f"Going to {self.describe(event)}: it starts now ({target.strftime('%H:%M')}).")
            if self.is_mockup and event.start_at.date() == self.today():
                self.state.mock_cursor_uid = event.uid
            if not self.calibrate(event, target):
                return
            # The operator says it has started: announce if needed, then pin it.
            if self.main_due(event, self.now()):
                self.post_main(event, self.now())
            if self.purpose_due(event, self.now()):
                self.post_purpose(event, self.now())
            self.state.started[event.uid] = target
            self.save()
            self.print_status()
            return

        say(f"Unknown command: {line!r}. Type `help`.")

    def run_calibration(self, event: ScheduledEvent, target: datetime) -> None:
        say(f"Calibrating {self.describe(event)} to start at {target.strftime('%H:%M')}.")
        self.calibrate(event, target)
        self.print_status()

    def fast_forward(self, delta: timedelta) -> None:
        # Step like real time passing, so announcements go out in order with correct t_minus.
        target = self.now() + delta
        say(f"Fast-forwarding to {target.strftime('%H:%M')}...")
        while self.now() < target:
            step = min(timedelta(seconds=MAX_SLEEP_SECONDS), target - self.now())
            self.fake_time_offset += step
            self.tick()

    # ---------- startup ----------

    def start(self) -> None:
        with self.lock:
            say(f"Loaded {len(self.events)} events; "
                f"{sum(e.start_at.date() == self.today() for e in self.events)} today.")
            self.load_or_recover()
            now = self.now()
            self.clear_stale_offset(now)
            if self.is_mockup and self.state.mock_cursor_uid is not None:
                cursor_event = self.by_uid.get(self.state.mock_cursor_uid)
                if cursor_event is None or cursor_event.start_at.date() < self.today():
                    self.state.mock_cursor_uid = None
            if self.is_mockup and self.state.mock_cursor_uid is None:
                before_today = [e for e in self.events if e.start_at.date() < self.today()]
                if before_today:
                    self.state.mock_cursor_uid = before_today[-1].uid
            self.freeze_started(now)
            self.save()
            self.print_status()
            stale = self.find_stale(now)
            if stale:
                self.ask_about_stale(stale)
            say("Type `help` for commands.")
        threading.Thread(target=self.scheduler_loop, daemon=True).start()


def run_shell(bot: AnnouncementBot) -> None:
    if not sys.stdin.isatty():
        for line in sys.stdin:
            bot.handle_command(line)
        return
    from prompt_toolkit import PromptSession
    from prompt_toolkit.patch_stdout import patch_stdout

    session: PromptSession[str] = PromptSession()
    prompt = "mockup> " if bot.is_mockup else "announce> "
    with patch_stdout():
        while True:
            try:
                line = session.prompt(prompt)
            except KeyboardInterrupt:
                continue
            except EOFError:
                break
            bot.handle_command(line)
    say("Bye.")


def run(site_data_path: str, is_mockup: bool = False, is_testing: bool = False) -> None:
    events = load_events(site_data_path)
    if not events:
        raise RuntimeError(f"No announceable events found in {site_data_path}/events.csv.")

    if is_testing:
        load_dotenv(dotenv_path=Path(".") / ".env")
        if os.environ.get(BOT_TOKEN_ENV_VAR, "").strip():
            sys.exit(
                f"--testing refuses to run while {BOT_TOKEN_ENV_VAR} is set "
                "(environment or .env). Unset it and retry."
            )
        announcements_channel_id = "ANNOUNCEMENTS"
        bot_home_channel_id = "BOT_HOME"
        client: Any = StdoutSlackClient({
            announcements_channel_id: ANNOUNCEMENTS_CHANNEL,
            bot_home_channel_id: BOT_HOME_CHANNEL,
            **{event.channel_id: event.title for event in events},
        })
        reporter.connect(client, bot_home_channel_id)
    else:
        client = create_slack_client(is_mockup=is_mockup)
        reporter.connect(client)
        announcements_channel_id = retry_until_success(
            f"finding #{ANNOUNCEMENTS_CHANNEL}", find_channel_id, client, ANNOUNCEMENTS_CHANNEL,
        )
        retry_until_success(
            f"joining #{ANNOUNCEMENTS_CHANNEL}",
            join_channel_if_needed, client, announcements_channel_id,
        )

    reporter.deliver("I awake!")
    suffix = ("_mockup" if is_mockup else "") + ("_testing" if is_testing else "")
    state_path = STATE_DIR / f"announcement_bot_state{suffix}.json"
    bot = AnnouncementBot(
        events, client, announcements_channel_id, state_path, is_mockup,
        is_testing=is_testing,
    )
    if is_testing:
        global stamp_clock
        stamp_clock = bot.now
    bot.start()
    run_shell(bot)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mockup",
        action="store_true",
        help="Use sitedata_mock. Requires mockup.env to be loaded.",
    )
    parser.add_argument(
        "--testing",
        action="store_true",
        help="Fake wall time (fast-forward with `+{m}`); print Slack posts to stdout instead.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        run(
            "sitedata_mock" if args.mockup else "sitedata",
            is_mockup=args.mockup, is_testing=args.testing,
        )
    except Exception:
        reporter.report("running the bot (fatal, exiting)")
        raise
    finally:
        try:
            if reporter.client is not None:
                reporter.deliver("I exit.")
        finally:
            reporter.print_undelivered()


if __name__ == "__main__":
    main()
