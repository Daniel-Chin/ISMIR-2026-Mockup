"""Build the assistant catalogue JSON from sitedata/*.csv.

The catalogue is the ONLY bridge between provisioning and the bot
(LLM_plan.md section 3). Reads the same CSVs as main.py, strips every
private column, and emits catalogue-<version>.json.

Usage (from the repo root, same env as main.py):

    python catalogue/build_catalogue.py --path sitedata/ --out-dir build/catalogue/
    python catalogue/build_catalogue.py --path sitedata_mock/   # mock pipeline

Fails (exit 1) if schema validation finds problems — including any private
value leaking into the output.
"""

import argparse
import csv
import datetime
import json
import os
import re
import sys

import pytz

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from catalogue.schema import validate_catalogue  # noqa: E402
from utils.session_assignment import parse_file  # noqa: E402
from utils.shared import load_conference_timezone_name, load_site_config  # noqa: E402

PRIVATE_COLUMNS = (
    "author_emails",
    "primary_email",
    "organiser_emails",
    "registered_emails",
    "review1",
    "review2",
    "review3",
    "review4",
    "meta_review",
)


# --- helpers copied from main.py (importing main.py would pull in Flask and
# --- module-level app setup; these are small and stable) -------------------


def remove_nested_parens_and_braces(s):
    while True:
        new = re.sub(r"\s*(\([^()]*\)|\{[^{}]*\})\*?", "", s)
        if new == s:
            return new
        s = new


def author_names(authors_and_affil):
    """'Name (Affil)*; Name2 (Affil2)' -> ['Name', 'Name2'] (main.py:remove_affiliation)."""
    clean = remove_nested_parens_and_braces(authors_and_affil)
    clean = re.sub(r"\s+", " ", clean)
    clean = clean.replace(",", ";")
    return [n.strip() for n in clean.split(";") if n.strip()]


def affiliations_of(authors_and_affil):
    """Unique affiliations from the (...) groups, in order of appearance."""
    seen = []
    for match in re.findall(r"\(([^()]*)\)", authors_and_affil):
        aff = match.strip()
        if aff and aff not in seen:
            seen.append(aff)
    return seen


def split_subjects(*fields):
    """Split 'A -> b; C -> d' subject columns into keywords (main.py:extract_list_field)."""
    keywords = []
    for value in fields:
        for part in sum([x.split("->") for x in (value or "").split(";")], []):
            part = part.strip()
            part = part[:1].upper() + part[1:] if part else part
            if part and part not in keywords:
                keywords.append(part)
    return keywords


def convert_drive_link(s):
    if "drive.google.com" in (s or ""):
        match = re.search(r"id=([^&]+)", s)
        if match:
            return "https://drive.google.com/file/d/{}/preview".format(match.group(1))
    return s or ""


# --- catalogue-specific parsing --------------------------------------------


def slack_channel_id(channel_url):
    """Extract the channel ID from either channel_url form utils/slack.py writes.

    - https://slack.com/app_redirect?channel=C09F3ARALJ0
    - https://<workspace>.slack.com/archives/C09F3ARALJ0
    """
    if not channel_url:
        return ""
    match = re.search(r"[?&]channel=([A-Z0-9]+)", channel_url)
    if match:
        return match.group(1)
    match = re.search(r"/archives/([A-Z0-9]+)", channel_url)
    if match:
        return match.group(1)
    return ""


def lbd_author_names(authors_field):
    """LBD authors come as 'Last, First; Last, First' or plain names (main.py:format_lbd)."""
    names = []
    for x in (authors_field or "").split(";"):
        x = x.strip()
        if not x:
            continue
        if "," in x:
            x = " ".join(reversed(x.replace(" ", "").replace("*", "").split(",")))
        else:
            x = x.replace("*", "")
        names.append(x)
    return names


def to_int(value):
    return int(str(value).strip())


def is_true(value):
    return str(value).strip().upper() == "TRUE"


def read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return [row for row in csv.DictReader(f)]


def to_utc(date_str, time_str, conf_tz):
    """'2026-07-20', '9:00' (conference-local) -> '2026-07-20T05:00:00+00:00'."""
    if not date_str or not time_str:
        raise ValueError("Session date and time are required")
    hour, minute = [int(x) for x in time_str.strip().split(":")[:2]]
    day_offset = 0
    if hour >= 24:  # '24:00' style end times
        hour -= 24
        day_offset = 1
    local = datetime.datetime.strptime(
        date_str.strip(), "%Y-%m-%d"
    ) + datetime.timedelta(days=day_offset, hours=hour, minutes=minute)
    return conf_tz.localize(local).astimezone(pytz.UTC).isoformat()


SESSION_TITLE_RE = re.compile(r"^(Oral|Poster) Session\s*-\s*(\d+)", re.IGNORECASE)


def build_papers(rows, base_url, assignments):
    papers = []
    for row in rows:
        if not (row.get("uid") or "").strip() or not (row.get("title") or "").strip():
            continue
        uid = row["uid"].strip()
        if uid not in assignments:
            raise ValueError("Papers missing from session_assignment.csv: " + uid)
        assignment = assignments[uid]
        papers.append(
            {
                "id": uid,
                "title": row["title"].strip(),
                "authors": author_names(row.get("authors_and_affil", "")),
                "affiliations": affiliations_of(row.get("authors_and_affil", "")),
                "abstract": (row.get("abstract") or "").strip(),
                "keywords": split_subjects(
                    row.get("primary_subject"), row.get("secondary_subject")
                ),
                "day": assignment.day,
                "session": assignment.session_index,
                "position": assignment.position,
                "session_id": "P{}".format(assignment.session_index),
                "summary_of_updates_post_review": (
                    row.get("summary_of_updates_post_review") or ""
                ).strip(),
                "slack_channel_name": (row.get("slack_channel") or "").strip(),
                "slack_channel_id": slack_channel_id(row.get("channel_url")),
                "miniconf_url": "{}/poster_{}.html".format(base_url, uid),
                "pdf_url": convert_drive_link(row.get("pdf_path")),
                "special_track": is_true(row.get("SpecialTrack")),
                "award_nominee": is_true(row.get("AwardNominee")),
                "is_tismir": is_true(row.get("is_tismir")),
            }
        )
    return papers


def build_lbds(rows, base_url):
    items = []
    for row in rows:
        if not (row.get("uid") or "").strip() or not (row.get("title") or "").strip():
            continue
        uid = row["uid"].strip()
        items.append(
            {
                "id": uid,
                "title": row["title"].strip(),
                "authors": lbd_author_names(row.get("authors", "")),
                "affiliations": [
                    a.strip()
                    for a in (row.get("affiliations") or "").split(";")
                    if a.strip()
                ],
                "abstract": (row.get("abstract") or "").strip(),
                "keywords": split_subjects(
                    row.get("primary_subject"), row.get("secondary_subject")
                ),
                "session": (row.get("session") or "").strip(),
                "slack_channel_name": (row.get("channel_name") or "").strip(),
                "slack_channel_id": slack_channel_id(row.get("channel_url")),
                "miniconf_url": "{}/lbd_{}.html".format(base_url, uid),
                "pdf_url": convert_drive_link(row.get("paper_link")),
            }
        )
    return items


def build_music(rows, base_url):
    items = []
    for row in rows:
        if not (row.get("uid") or "").strip() or not (row.get("title") or "").strip():
            continue
        uid = row["uid"].strip()
        items.append(
            {
                "id": uid,
                "title": row["title"].strip(),
                "authors": [
                    a.strip()
                    for a in (row.get("authors") or "").split(";")
                    if a.strip()
                ],
                "affiliations": [
                    a.strip()
                    for a in (row.get("affiliation") or "").split(";")
                    if a.strip()
                ],
                "abstract": (row.get("abstract") or "").strip(),
                "keywords": [],
                "session": (row.get("session") or "").strip(),
                "slack_channel_name": (row.get("channel_name") or "").strip(),
                "slack_channel_id": slack_channel_id(row.get("channel_url")),
                "miniconf_url": "{}/music_{}.html".format(base_url, uid),
                "web_link": (row.get("web_link") or "").strip(),
            }
        )
    return items


def build_industry(rows, base_url):
    items = []
    for row in rows:
        if not (row.get("uid") or "").strip() or not (row.get("title") or "").strip():
            continue
        uid = row["uid"].strip()
        items.append(
            {
                "id": uid,
                "title": row["title"].strip(),
                "company": (row.get("company") or "").strip(),
                "authors": [
                    r.strip() for r in (row.get("rep") or "").split(";") if r.strip()
                ],
                "affiliations": (
                    [(row.get("company") or "").strip()]
                    if (row.get("company") or "").strip()
                    else []
                ),
                "abstract": (row.get("abstract") or "").strip(),
                "keywords": [],
                "session": (row.get("session") or "").strip(),
                "slack_channel_name": (row.get("channel_name") or "").strip(),
                "slack_channel_id": slack_channel_id(row.get("channel_url")),
                "miniconf_url": "{}/industry_{}.html".format(base_url, uid),
                "external_web_link": (row.get("external_web_link") or "").strip(),
            }
        )
    return items


def build_sessions(rows, papers, conf_tz):
    """events.csv rows -> sessions. Paper session numbers join to
    'Oral/Poster Session - N' titles; validate this against 2026 data."""
    papers_by_session = {}
    for paper in papers:
        papers_by_session.setdefault(paper["session"], []).append(paper["id"])

    sessions = []
    for row in rows:
        if not (row.get("uid") or "").strip() or not (row.get("title") or "").strip():
            continue
        title = row["title"].strip()
        match = SESSION_TITLE_RE.match(title)
        paper_ids = []
        if match:
            session_id = "{}{}".format(match.group(1)[0].upper(), int(match.group(2)))
            paper_ids = papers_by_session.get(int(match.group(2)), [])
        else:
            session_id = "E{}".format(row["uid"].strip())
        sessions.append(
            {
                "id": session_id,
                "title": title,
                "type": (row.get("category") or "").strip(),
                "day": to_int(row.get("day")),
                "start_utc": to_utc(
                    row.get("start_date"), row.get("start_time"), conf_tz
                ),
                "end_utc": to_utc(
                    row.get("start_date"), row.get("end_time"), conf_tz
                ),
                "location": "",  # not in events.csv; fill when 2026 adds venues
                "description": (row.get("description") or "").strip(),
                "slack_channel_name": (row.get("slack_channel") or "").strip(),
                "slack_channel_id": slack_channel_id(row.get("channel_url")),
                "paper_ids": paper_ids,
            }
        )
    return sessions


def build_logistics(rows):
    return [
        {
            "id": (row.get("id") or "").strip(),
            "title": (row.get("title") or "").strip(),
            "body": (row.get("body") or "").strip(),
        }
        for row in rows
        if (row.get("id") or "").strip()
    ]


def collect_private_values(sitedata):
    """All non-empty values of private columns across every CSV, so we can
    assert none of them appear anywhere in the serialized catalogue."""
    values = set()
    for name in ("papers", "lbds", "music", "industry", "events"):
        for row in read_csv(os.path.join(sitedata, name + ".csv")):
            for col in PRIVATE_COLUMNS:
                value = (row.get(col) or "").strip()
                if len(value) > 3:  # skip trivial values like 'no'
                    values.add(value)
    return values


def build(sitedata, base_url, version):
    config = load_site_config(sitedata)
    config_timezone = load_conference_timezone_name(sitedata)
    conf_tz = pytz.timezone(config_timezone)

    _, assigned_papers = parse_file(sitedata)
    assignments = {paper.uid: paper for paper in assigned_papers}
    papers = build_papers(read_csv(os.path.join(sitedata, "papers.csv")), base_url, assignments)
    catalogue = {
        "version": version,
        "conference": {
            "name": config["name"],
            "timezone": config_timezone,
            "site_base_url": base_url,
        },
        "embedding_model": "",  # filled in by build_index.py
        "papers": papers,
        "lbds": build_lbds(read_csv(os.path.join(sitedata, "lbds.csv")), base_url),
        "music": build_music(read_csv(os.path.join(sitedata, "music.csv")), base_url),
        "industry": build_industry(
            read_csv(os.path.join(sitedata, "industry.csv")), base_url
        ),
        "sessions": build_sessions(
            read_csv(os.path.join(sitedata, "events.csv")), papers, conf_tz
        ),
        "logistics": build_logistics(read_csv(os.path.join(sitedata, "logistics.csv"))),
    }
    return catalogue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default="sitedata/", help="sitedata directory")
    parser.add_argument("--out-dir", default="build/catalogue/")
    parser.add_argument(
        "--site-base-url",
        default=None,
        help="production MiniConf base URL (default: config miniconf_url)",
    )
    parser.add_argument(
        "--version", default=datetime.date.today().isoformat(), help="YYYY-MM-DD"
    )
    args = parser.parse_args()

    base_url = (
        args.site_base_url or load_site_config(args.path.rstrip("/"))["miniconf_url"]
    ).rstrip("/")
    catalogue = build(args.path.rstrip("/"), base_url, args.version)

    validate_catalogue(catalogue)
    errors = []
    serialized = json.dumps(catalogue, ensure_ascii=False, indent=1)
    for value in collect_private_values(args.path.rstrip("/")):
        if value in serialized:
            errors.append(
                "private value leaked into catalogue: {!r}...".format(value[:40])
            )
    if errors:
        raise ValueError("Invalid catalogue: " + "; ".join(errors))

    # Operational warnings (not fatal pre-provisioning: channel_urls are
    # filled by miniconf_prep.py setup-* actions)
    for kind in ("papers", "lbds"):
        missing = [i["id"] for i in catalogue[kind] if not i["slack_channel_id"]]
        if missing:
            print(
                "WARNING: {}/{} {} missing slack_channel_id (run Slack prep?): {}".format(
                    len(missing), len(catalogue[kind]), kind, missing[:10]
                ),
                file=sys.stderr,
            )
    if not catalogue["logistics"]:
        print(
            "WARNING: no logistics.csv found — logistics list is empty", file=sys.stderr
        )

    os.makedirs(args.out_dir, exist_ok=True)
    out_path = os.path.join(args.out_dir, "catalogue-{}.json".format(args.version))
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(serialized)
    print(
        "wrote {} ({} papers, {} lbds, {} music, {} industry, {} sessions, {} logistics)".format(
            out_path,
            len(catalogue["papers"]),
            len(catalogue["lbds"]),
            len(catalogue["music"]),
            len(catalogue["industry"]),
            len(catalogue["sessions"]),
            len(catalogue["logistics"]),
        )
    )


if __name__ == "__main__":
    main()
