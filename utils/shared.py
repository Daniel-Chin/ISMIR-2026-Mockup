from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import cast, overload
from zoneinfo import ZoneInfo

import yaml


@lru_cache(maxsize=32)
def load_site_config(site_data_path: str) -> dict:
    config_path = Path(site_data_path) / "config.yml"
    with config_path.open(encoding="utf-8") as handle:
        config = yaml.safe_load(handle)
    if not isinstance(config, dict) or not config:
        raise ValueError(f"Site configuration must be a nonempty mapping: {config_path}")
    return config


def parse_award_nominee(value: str) -> tuple[int, int] | None:
    """papers.csv AwardNominee: 'A{session}-{position}' -> (session, position); 'No' -> None."""
    value = value.strip()
    if value == "No":
        return None
    match = re.fullmatch(r"A(\d+)-(\d+)", value)
    if not match:
        raise ValueError(f"Invalid AwardNominee: {value!r}")
    return int(match.group(1)), int(match.group(2))


SESSION_KINDS = {"Poster session": "poster", "Oral session": "oral"}
NO_PAGE_CATEGORIES = {"Registration", "Lunch"}


def event_link(event: dict) -> str:
    """Relative URL of the event's page, or "" if it has none."""
    kind = SESSION_KINDS.get(event["category"])
    if kind:
        return f"papers.html?session={event['title'].split()[-1]}&type={kind}"
    if event["category"] in NO_PAGE_CATEGORIES:
        return ""
    if not any(str(event.get(k) or "").strip()
               for k in ("event_desc", "channel_url", "live_url")):
        return ""
    return f"event_{event['uid']}.html"


def calendar_ics_path(site_data_path: str) -> str:
    """Relative to the repo root, e.g. static/calendar/ISMIR_2026.ics"""
    name = str(load_site_config(site_data_path)["name"])
    return f"static/calendar/{name.replace(' ', '_')}.ics"


def parse_conference_dates(config: dict) -> tuple[date, date]:
    """First and last conference day from config["date"], e.g. '2026 Nov 8-12'"""
    year, month, day_range = str(config["date"]).split(" ")
    first_day, last_day = day_range.split("-")
    month_number = datetime.strptime(month, "%b").month  # noqa: DTZ007
    return (
        date(int(year), month_number, int(first_day)),
        date(int(year), month_number, int(last_day)),
    )


def load_helpdesk_url(site_data_path: str) -> str:
    return str(load_site_config(site_data_path)["helpdesk_url"])


@lru_cache(maxsize=32)
def load_conference_timezone_name(
    site_data_path: str,
) -> str:
    config = load_site_config(site_data_path)
    return str(config["timezone"])


def load_conference_timezone(
    site_data_path: str,
) -> ZoneInfo:
    timezone_name = load_conference_timezone_name(site_data_path)
    return ZoneInfo(timezone_name)


def _timezone_label(dt: datetime, timezone_name: str) -> str:
    display_name = timezone_name.rsplit("/", 1)[-1].replace("_", " ")
    offset = dt.strftime("%z")
    if len(offset) == 5:
        hours = int(offset[1:3])
        minutes = f":{offset[3:]}" if offset[3:] != "00" else ""
        return f"(GMT{offset[0]}{hours}{minutes}, {display_name})"
    return f"({display_name})"


def _normalize_session_datetime(dt: datetime, zone_info: ZoneInfo) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=zone_info)
    return dt.astimezone(zone_info)


def _format_session_window_datetimes(
    start_datetime: datetime,
    end_datetime: datetime | None,
    zone_info: ZoneInfo,
) -> str:
    start_local = _normalize_session_datetime(start_datetime, zone_info)
    end_local = (
        _normalize_session_datetime(end_datetime, zone_info)
        if end_datetime is not None else None
    )
    tz_label = _timezone_label(start_local, zone_info.key)

    if end_local is not None and start_local.date() != end_local.date():
        return (
            f"{start_local.strftime('%a, %b %d, %H:%M')} - "
            f"{end_local.strftime('%a, %b %d, %H:%M')} "
            f"{tz_label}"
        )

    end_label = end_local.strftime('%H:%M') if end_local is not None else 'TBD'
    return (
        f"{start_local.strftime('%a, %b %d')}, "
        f"{start_local.strftime('%H:%M')}-{end_label} "
        f"{tz_label}"
    )


@overload
def format_session_window(
    start_date: str | None,
    start_time: str | None,
    end_time: str | None,
    timezone_name: str,
    /,
) -> str:
    ...


@overload
def format_session_window(
    start_datetime: datetime,
    end_datetime: datetime | None,
    zone_info: ZoneInfo,
    /,
) -> str:
    ...


def format_session_window(
    *args: str | datetime | ZoneInfo | None,
) -> str:
    """Format a session window in the specified timezone.

    Examples:
        >>> format_session_window("2026-01-01", "09:00", "10:30", "UTC")
        'Thu, Jan 01, 09:00-10:30 (GMT+0, UTC)'
        >>> format_session_window("2026-01-01", "23:30", "00:15", "UTC")
        'Thu, Jan 01, 23:30 - Fri, Jan 02, 00:15 (GMT+0, UTC)'
    """
    if len(args) == 3 and isinstance(args[0], datetime):
        start_datetime, end_datetime, zone_info = args
        if end_datetime is not None and not isinstance(end_datetime, datetime):
            raise TypeError("end_datetime must be a datetime or None")
        if not isinstance(zone_info, ZoneInfo):
            raise TypeError("zone_info must be a ZoneInfo")

        return _format_session_window_datetimes(
            cast(datetime, start_datetime),
            end_datetime,
            zone_info,
        )

    if len(args) != 4:
        raise TypeError("format_session_window expects either 3 or 4 positional arguments")

    start_date, start_time, end_time, timezone_name = args

    if not start_date or not start_time or not end_time:
        raise ValueError("Session date, start time and end time must be valid and nonempty")
    if timezone_name is None or not isinstance(timezone_name, str):
        raise TypeError("timezone_name is required with string inputs")

    tz = ZoneInfo(timezone_name)

    try:
        year, month, day = [int(x) for x in str(start_date).split("-")]
        start_hour, start_minute = [int(x) for x in str(start_time).split(":")[:2]]
        start_local = datetime(year, month, day, start_hour, start_minute, tzinfo=tz)
        end_local = None
        if end_time != 'tbd':
            end_hour, end_minute = [int(x) for x in str(end_time).split(":")[:2]]
            end_local = datetime(year, month, day, end_hour, end_minute, tzinfo=tz)
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid session date or time") from exc

    if end_local is not None and end_local < start_local:
        end_local += timedelta(days=1)

    return _format_session_window_datetimes(start_local, end_local, tz)
