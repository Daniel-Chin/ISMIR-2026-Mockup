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
SHARED = ROOT.parent / "shared"   # used by the Live Overview too
# Copied into public/vendor/ (generated, gitignored): the live overview's stylesheet, so both sites
# look the same, and the files both sites share.
VENDORED = {
    OVERVIEW_SOURCE / "styles.css": "overview.css",
    SHARED / "timezone-preference.js": "timezone-preference.js",
    SHARED / "site-chrome.js": "site-chrome.js",
    SHARED / "canon-egg.js": "canon-egg.js",
}
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


# Paper materials, by the miniconf poster-page section that shows them (poster_<uid>.html#<id>).
# Same conditions as templates/poster.html: the section exists only when its column is filled.
# (The page embeds them, so no raw Drive links leave the build.)
MATERIAL_SECTIONS = [("paper", "raw_pdf_path"), ("poster", "raw_poster_pdf"), ("video", "video")]
# The same for LBDs (lbds.csv, shown at lbd_<uid>.html#<id>; conditions as in templates/lbd.html).
# The real LBD sheet has the papers' columns; the mock one its own (second name), as main.py format_lbd.
LBD_MATERIAL_SECTIONS = [("paper", ("raw_pdf_path", "paper_link")), ("poster", ("raw_poster_pdf", "poster_link")),
                         ("video", ("video_path", "youtube_id"))]


def lbd_authors(raw):
    """'Last, First; Last, First' -> 'First Last; First Last', as main.py format_lbd shows them."""
    names = []
    for part in (raw or "").split(";"):
        part = part.replace("*", "").strip()
        if "," in part:
            last, _, first = part.partition(",")
            part = f"{first.strip()} {last.strip()}"
        if part:
            names.append(re.sub(r"\s+", " ", part))
    return "; ".join(names) or "Authors TBA"


def lbd_presenter_mode(row):
    """Real sheet: presentation_mode ("Virtual", "In-Person"); mock: Slack lp-* / lv-* channels."""
    if (row.get("presentation_mode") or "").strip():
        mode = row["presentation_mode"].strip().lower()
        return "" if "not answered" in mode else presenter_mode(mode)
    return {"lp": "onsite", "lv": "online"}.get((row.get("channel_name") or "").strip().lower()[:2], "")


def read_lbds(sd, miniconf):
    """All LBDs, in programme order (position, else CMT id). They share one session, so they are not grouped.

    Boards and links use the CMT id (uid), as the miniconf's lbd_<uid>.html pages do.
    """
    path = sd / "lbds.csv"
    if not path.is_file():
        return []
    with open(path, encoding="utf-8", newline="") as f:
        rows = [r for r in csv.DictReader(f) if re.fullmatch(r"\d{1,6}", (r.get("uid") or "").strip())]

    def order(r):
        pos = (r.get("position") or "").strip()
        return (int(pos) if pos.isdigit() else 10**9, int(r["uid"]))
    lbds = []
    for r in sorted(rows, key=order):
        uid = r["uid"].strip()
        lbds.append({
            "uid": uid,
            "displayId": f"LBD-{uid}",
            "title": (r.get("title") or "").strip(),
            "authors": overview_authors(r["authors_and_affil"]) if (r.get("authors_and_affil") or "").strip() else lbd_authors(r.get("authors", "")),
            "channelUrl": (r.get("channel_url") or "").strip(),
            "pageUrl": f"{miniconf}/lbd_{uid}.html" if miniconf else "",
            "presenterMode": lbd_presenter_mode(r),
            "materials": [section for section, cols in LBD_MATERIAL_SECTIONS if any((r.get(c) or "").strip() for c in cols)],
        })
    return lbds


def hhmm(value):
    """'9:00' -> '09:00' so times line up in the cards."""
    h, _, m = (value or "").strip().partition(":")
    return f"{int(h):02d}:{m}" if h.isdigit() else (value or "").strip()


def truthy(value):
    return str(value).strip().lower() in {"yes", "true", "1", "y"}


def flag_set(src, value):
    if src == "AwardNominee":  # "No" or "A{session}-{position}"
        return bool(re.fullmatch(r"A\d+-\d+", value.strip()))
    return truthy(value)


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
    slots, lbd_slot = {}, None
    with open(sd / "events.csv", encoding="utf-8", newline="") as f:
        for ev in csv.DictReader(f):
            if (ev.get("category") or "").strip().upper() == "LBD" and lbd_slot is None:
                lbd_slot = {"kind": "lbd", "date": ev["start_date"].strip(), "start": hhmm(ev["start_time"]), "end": hhmm(ev["end_time"])}
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
            paper["flags"] = [out for src, out in FLAG_FIELDS.items() if flag_set(src, row.get(src, ""))]
            paper["session"] = name
            paper["posterUrl"] = f"{miniconf}/poster_{uid}.html" if miniconf else ""
            # Overview card fields: "P1-01" ids, name-only authors, presenter mode, material links.
            paper["displayId"] = f"P{int(number.group())}-{pos:02d}" if number else f"#{uid}"
            paper["authors"] = overview_authors(row.get("authors_and_affil", ""))
            paper["presenterMode"] = presenter_mode(row.get("paper_presentation", ""))
            paper["materials"] = [section for section, col in MATERIAL_SECTIONS if row.get(col, "").strip()]
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
            "venueCity": config.get("venue_city", ""),
            "slackAppName": config.get("slack_app_name", ""),
        },
        "days": days,
        "sessions": {s["id"]: s for s in sessions},
        "papers": papers,
        # One session for every LBD: its time, and the LBDs in programme order.
        "lbdSession": {"id": "LBD", "slots": [lbd_slot] if lbd_slot else []},
        "lbds": read_lbds(sd, miniconf),
    }

    out_json = ROOT / "public" / "data" / "program.json"
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(program, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    vendor = ROOT / "public" / "vendor"
    vendor.mkdir(parents=True, exist_ok=True)
    for src, dst in VENDORED.items():
        data = src.read_bytes()
        if dst == "overview.css":
            # The overview scopes its paper-card styles to #live-events; the LBD Hall's grid
            # (#lbd-grid) is on the page at the same time as an open session's, so it gets them too.
            data = data.replace(b"#live-events", b":is(#live-events, #lbd-grid)")
        (vendor / dst).write_bytes(data)

    print(f"{len(sessions)} sessions, {len(papers)} papers, {len(program['lbds'])} LBDs -> {out_json.relative_to(ROOT)}")
    if missing:
        print(f"WARNING: {len(missing)} assigned uids missing from papers.csv: {', '.join(missing)}")


if __name__ == "__main__":
    main()
