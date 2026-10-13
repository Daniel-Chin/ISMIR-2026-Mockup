"""Freeze ../sitedata into what the pre-conference lounge front end needs.

public/data/program.json   -> what the browser renders (public paper fields only; never reviews)
public/vendor/             -> live overview's stylesheet + time-zone picker, so both sites look the same

The Worker does not read this: it validates rooms and boards by pattern (src/rooms.js), so paper
data can change on every GitHub Action run without redeploying the backend.

Run from anywhere:  python preconf/scripts/build_data.py [--sitedata DIR]
"""
import argparse
import csv
import datetime as dt
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SITEDATA = ROOT.parent / "sitedata"
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Only these columns ever leave the build machine. Reviews, raw paths etc. stay private.
PUBLIC_FIELDS = {
    "uid": "uid",
    "title": "title",
    "authors_and_affil": "authors",
    "abstract": "abstract",
    "primary_subject": "primarySubject",
    "secondary_subject": "secondarySubject",
    "paper_presentation": "presentation",
    "slack_channel": "slackChannel",
    "channel_url": "channelUrl",
    "fun_facts": "funFact",  # author-provided; shown by the piano easter egg, as on the live overview
}
OVERVIEW_SOURCE = ROOT.parent / "live_overview" / "overview-source"
VENDORED = {"styles.css": "overview.css", "timezone-preference.js": "timezone-preference.js"}
FLAG_FIELDS = {"StudentAuthor": "student", "AwardNominee": "award", "is_tismir": "tismir", "SpecialTrack": "special"}


def read_simple_yaml(path):
    """config.yml only needs a few top-level scalars; avoid a PyYAML dependency."""
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        m = re.match(r"^([A-Za-z_][\w]*)\s*:\s*(.*?)\s*(#.*)?$", line)
        if m and m.group(2):
            out[m.group(1)] = m.group(2).strip("'\"")
    return out


def conference_dates(text):
    """'2026 Nov 8-12' -> {weekday: iso date}."""
    m = re.match(r"(\d{4})\s+(\w{3})\w*\s+(\d+)\s*-\s*(\d+)", text or "")
    if not m:
        return {}
    year, month, first, last = int(m.group(1)), dt.datetime.strptime(m.group(2), "%b").month, int(m.group(3)), int(m.group(4))
    days = {}
    for d in range(first, last + 1):
        date = dt.date(year, month, d)
        days[WEEKDAYS[date.weekday()]] = date.isoformat()
    return days


def overview_authors(raw):
    """Names only, '; '-separated, as the live overview shows them.

    Affiliations can nest parentheses ("(National Institute ... (AIST))") and contain ';'
    ("(FIST, XJTU; IRC ..., XJTU)"), so text inside parentheses is dropped by depth, and
    authors are split only on ';' at depth 0.
    """
    names, current, depth = [], [], 0
    for ch in raw or "":
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif depth == 0:
            if ch == ";":
                names.append("".join(current))
                current = []
            else:
                current.append(ch)
    names.append("".join(current))
    names = [re.sub(r"\s+", " ", n.replace("*", "")).strip() for n in names]
    return "; ".join(n for n in names if n) or "Authors TBA"


def presenter_mode(raw):
    """Same buckets as the live overview (csv_helpers.normalize_presenter_mode); '' when unknown."""
    s = (raw or "").strip().lower()
    if not s:
        return ""
    if any(k in s for k in ("virtual", "online", "remote")):
        return "online"
    if "hybrid" in s or "mixed" in s:
        return "mixed"
    return "onsite"


# Paper materials, exactly the ones the live overview links (https only).
MATERIAL_LINKS = [("raw_pdf_path", "pdf"), ("raw_video", "video"), ("raw_poster_pdf", "poster"), ("raw_slides_pdf", "slides")]


def hhmm(value):
    """'9:00' -> '09:00' so times line up in the cards."""
    h, _, m = (value or "").strip().partition(":")
    return f"{int(h):02d}:{m}" if h.isdigit() else (value or "").strip()


def truthy(value):
    return str(value).strip().lower() in {"yes", "true", "1", "y"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sitedata", type=Path, default=DEFAULT_SITEDATA)
    args = ap.parse_args()
    sd = args.sitedata

    config = read_simple_yaml(sd / "config.yml")
    dates = conference_dates(config.get("date", ""))
    miniconf = config.get("miniconf_url", "").rstrip("/")

    csv.field_size_limit(10**9)
    with open(sd / "papers.csv", encoding="utf-8", newline="") as f:
        papers_by_uid = {row["uid"].strip(): row for row in csv.DictReader(f)}

    # "Oral Session - 1" / "Poster Session - 1" in events.csv: each session's papers get a short
    # oral slot and a poster slot. Same title match as live_overview/scripts/update_schedule.py.
    slots = {}
    with open(sd / "events.csv", encoding="utf-8", newline="") as f:
        for ev in csv.DictReader(f):
            m = re.fullmatch(r"(Poster|Oral)\s+Session\s*-?\s*(\d+)", (ev.get("title") or "").strip(), re.I)
            if m:
                slots.setdefault(int(m.group(2)), {})[m.group(1).lower()] = {
                    "date": ev["start_date"].strip(), "start": hhmm(ev["start_time"]), "end": hhmm(ev["end_time"])}

    with open(sd / "session_assignment.csv", encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))
    table = {r[0].strip(): r[1:] for r in rows if r}
    names = table["Session Name"]
    times = table.get("Session Day & Time (UTC+4)", [""] * len(names))
    paper_rows = [k for k in table if re.fullmatch(r"Paper-\d+", k)]
    paper_rows.sort(key=lambda k: int(k.split("-")[1]))

    sessions, papers, missing = [], {}, []
    for col, name in enumerate(names):
        name = name.strip()
        if not name:
            continue
        when = times[col].strip() if col < len(times) else ""
        m = re.match(r"(\w{3}),\s*(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", when)
        day, start, end = (m.group(1), m.group(2), m.group(3)) if m else ("TBA", "", "")
        uids = []
        number = re.search(r"\d+", name)
        for pos, key in enumerate(paper_rows, start=1):
            uid = table[key][col].strip() if col < len(table[key]) else ""
            if not uid:
                continue
            row = papers_by_uid.get(uid)
            if row is None:
                missing.append(uid)
                continue
            uids.append(uid)
            paper = {out: row.get(src, "").strip() for src, out in PUBLIC_FIELDS.items()}
            paper["flags"] = [out for src, out in FLAG_FIELDS.items() if truthy(row.get(src, ""))]
            paper["session"] = name
            paper["posterUrl"] = f"{miniconf}/poster_{uid}.html" if miniconf else ""
            # Overview card fields: "P1-01" ids, name-only authors, presenter mode, material links.
            paper["displayId"] = f"P{int(number.group())}-{pos:02d}" if number else f"#{uid}"
            paper["authors"] = overview_authors(row.get("authors_and_affil", ""))
            paper["presenterMode"] = presenter_mode(row.get("paper_presentation", ""))
            paper["links"] = {dst: row[src].strip() for src, dst in MATERIAL_LINKS
                              if row.get(src, "").strip().startswith("https://")}
            papers[uid] = paper
        found = slots.get(int(number.group()), {}) if number else {}
        # Oral first, then poster; fall back to the combined window when events.csv lacks them.
        session_slots = [{"kind": k, **found[k]} for k in ("oral", "poster") if k in found] or \
            [{"kind": "session", "date": dates.get(day, ""), "start": start, "end": end}]
        sessions.append({"id": name, "day": day, "date": dates.get(day, ""), "start": start, "end": end,
                         "slots": session_slots, "papers": uids})

    day_order = {d: i for i, d in enumerate(WEEKDAYS)}
    days = []
    for s in sessions:
        if not days or days[-1]["day"] != s["day"]:
            days.append({"day": s["day"], "date": s["date"], "sessions": []})
        days[-1]["sessions"].append(s["id"])
    days.sort(key=lambda d: (d["date"] or "9999", day_order.get(d["day"], 99)))

    program = {
        "conference": {
            "name": config.get("name", "ISMIR"),
            "date": config.get("date", ""),
            "timezone": config.get("timezone", "UTC"),
            "miniconfUrl": miniconf,
            "officialSiteUrl": config.get("official_site_url", ""),
            "helpdeskUrl": config.get("helpdesk_url", ""),
        },
        "days": days,
        "sessions": {s["id"]: s for s in sessions},
        "papers": papers,
        "lbds": [],  # sitedata has no LBD table yet
    }

    out_json = ROOT / "public" / "data" / "program.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(program, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    vendor = ROOT / "public" / "vendor"
    vendor.mkdir(parents=True, exist_ok=True)
    for src, dst in VENDORED.items():
        (vendor / dst).write_bytes((OVERVIEW_SOURCE / src).read_bytes())

    print(f"{len(sessions)} sessions, {len(papers)} papers -> {out_json.relative_to(ROOT)}")
    if missing:
        print(f"WARNING: {len(missing)} assigned uids missing from papers.csv: {', '.join(missing)}")


if __name__ == "__main__":
    main()
