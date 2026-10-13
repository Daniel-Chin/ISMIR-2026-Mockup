#!/usr/bin/env python3
"""Row-level helpers for update_schedule.convert (events.csv, papers.csv).

Only public-facing fields are read. Paper rows never receive Zoom links;
a session's Zoom live_url belongs to the parent event.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo


def clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip()


def slugify(text: Any) -> str:
    s = clean_text(text).lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "item"


def strip_miro(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: strip_miro(v) for k, v in obj.items() if k != "miro"}
    if isinstance(obj, list):
        return [strip_miro(x) for x in obj]
    return obj


def parse_int(value: Any) -> int | None:
    s = clean_text(value)
    if not s:
        return None
    try:
        return int(float(s))
    except Exception:
        m = re.search(r"\d+", s)
        return int(m.group(0)) if m else None


def normalize_presenter_mode(value: Any) -> str:
    s = clean_text(value).lower()
    if "virtual" in s or "online" in s or "remote" in s:
        return "online"
    if "hybrid" in s or "mixed" in s:
        return "mixed"
    return "onsite"


def parse_authors(authors_and_affil: Any) -> str:
    raw = clean_text(authors_and_affil)
    if not raw:
        return "Authors TBA"
    # Affiliations may nest parentheses ("... (AIST))") and contain ';' ("FIST, XJTU; IRC, XJTU"),
    # so drop parenthesised text by depth and split authors only on ';' outside parentheses.
    parts, current, depth = [], [], 0
    for ch in raw:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif depth == 0:
            if ch == ";":
                parts.append("".join(current))
                current = []
            else:
                current.append(ch)
    parts.append("".join(current))
    names = [clean_text(part.replace("*", "")) for part in parts]
    names = [name for name in names if name]
    return "; ".join(names) if names else raw


def parse_subjects(row: dict[str, Any]) -> list[str]:
    subjects: list[str] = []
    for key in ("primary_subject", "secondary_subject"):
        value = clean_text(row.get(key))
        if not value:
            continue
        for item in value.split(";"):
            item = clean_text(item)
            if item and item not in subjects:
                subjects.append(item)
    return subjects


def event_type(title: str, category: str) -> str:
    t = title.lower()
    c = category.lower()
    if "poster session" in t:
        return "poster"
    if "oral session" in t:
        return "oral"
    if "keynote" in t:
        return "keynote"
    if "tutorial" in t:
        return "tutorial"
    if "lunch" in t or "lunch" in c:
        return "lunch"
    if "coffee" in t or "break" in c:
        return "break"
    if "registration" in t or "registration" in c:
        return "registration"
    if "late-breaking" in t or "demo" in t or c in {"lbd", "demo"}:
        return "demo"
    if "industry" in t or "industry" in c:
        return "industry"
    if "wimir" in t or "community" in c:
        return "community"
    if "unconference" in t:
        return "unconference"
    if any(x in t for x in ("banquet", "reception", "party")) or c == "social":
        return "social"
    if "concert" in t or "music program" in t or c in {"music", "performance"}:
        return "performance"
    if any(x in t for x in ("opening", "closing", "award")) or c in {"opening", "awards"}:
        return "ceremony"
    if "board" in t or "society meeting" in t:
        return "meeting"
    if "special session" in t:
        return "special"
    return "session"


def topic_from_event(typ: str, category: str) -> str:
    labels = {
        "poster": "Poster presentations",
        "oral": "Oral paper session",
        "keynote": "Keynote",
        "tutorial": "Tutorial",
        "lunch": "Break",
        "break": "Break",
        "industry": "Industry",
        "community": "Community",
        "demo": "Late-breaking / demo",
        "performance": "Music / performance",
        "social": "Social event",
        "ceremony": "Conference ceremony",
        "special": "Special session",
    }
    return labels.get(typ) or clean_text(category) or "Programme"


def parse_local_datetime(date_value: Any, time_value: Any, tz_name: str) -> datetime:
    date_text = clean_text(date_value)
    time_text = clean_text(time_value)
    if not date_text or not time_text:
        raise ValueError(f"Missing event date/time: date={date_text!r}, time={time_text!r}")
    parsed_date = datetime.strptime(date_text, "%Y-%m-%d").date()
    parsed_time = None
    for fmt in ("%H:%M", "%H:%M:%S"):
        try:
            parsed_time = datetime.strptime(time_text, fmt).time()
            break
        except ValueError:
            pass
    if parsed_time is None:
        raise ValueError(f"Unsupported time format: {time_text!r}")
    return datetime.combine(parsed_date, parsed_time, tzinfo=ZoneInfo(tz_name))


def build_paper(row: dict[str, Any], event_id: str, session_no: int, position: int) -> dict[str, Any]:
    # session_no/position come from session_assignment.csv; papers.csv's own columns are deprecated.
    uid = clean_text(row.get("uid"))
    pid = f"P{session_no}-{position:02d}" if session_no and position else f"P-{uid or slugify(row.get('title'))}"
    slack_slug = clean_text(row.get("slack_channel"))
    links: dict[str, str] = {}
    if clean_text(row.get("channel_url")):
        links["slack"] = clean_text(row.get("channel_url"))
    elif slack_slug:
        links["slack"] = slack_slug
    # Intentionally no Zoom link here. Poster Zoom belongs to the parent session.
    asset_map = {
        "pdf_path": "pdf",
        "video": "video",
        "poster_pdf": "poster",
        "slides_pdf": "slides",
        "thumbnail": "thumbnail",
    }
    for source_key, link_key in asset_map.items():
        value = clean_text(row.get(source_key))
        if value:
            links[link_key] = value
    aliases = [pid]
    if uid:
        aliases += [uid, f"uid-{uid}", f"paper-{uid}"]
    if session_no and position:
        aliases += [f"P{session_no}-{position}", f"S{session_no}-P{position}", f"session-{session_no}-position-{position}"]
    if slack_slug:
        aliases.append(slack_slug)
    paper = {
        "id": pid,
        "aliases": list(dict.fromkeys([a for a in aliases if a])),
        "sessionId": event_id,
        "sourcePaperId": uid,
        "sessionNumber": session_no,
        "posterSessionNumber": session_no,
        "sessionPaperNumber": position,
        "title": clean_text(row.get("title")),
        "authors": parse_authors(row.get("authors_and_affil")),
        "primaryAuthor": clean_text(row.get("primary_author")),
        "presenterMode": normalize_presenter_mode(row.get("paper_presentation")),
        "abstract": clean_text(row.get("abstract")),
        "funFact": clean_text(row.get("funfact") or row.get("fun_fact") or row.get("fun fact")),
        "subjects": parse_subjects(row),
        "isTismir": clean_text(row.get("is_tismir")).upper() == "TRUE",
        "longPresentation": clean_text(row.get("long_presentation")).upper() == "TRUE",
        "links": strip_miro(links),
    }
    return {k: v for k, v in paper.items() if v not in ("", [], None)}


def infer_conference(event_rows: list[dict[str, Any]], conf: dict[str, str]) -> dict[str, Any]:
    dates = [clean_text(r.get("start_date")) for r in event_rows if clean_text(r.get("start_date"))]
    return {
        "name": conf["name"],
        "timeZone": conf["timezone"],
        "startsOn": min(dates) if dates else "",
        "endsOn": max(dates) if dates else "",
        "pageTitle": f"{conf['name']} Live Overview",
    }
