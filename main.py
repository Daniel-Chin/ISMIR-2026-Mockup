# pylint: disable=global-statement,redefined-outer-name
import argparse
import csv
import datetime
import glob
import json
import os
import re
from functools import partial, reduce
from collections.abc import Callable
from urllib.parse import parse_qs, urlparse

from dotenv import load_dotenv

# from flaskext.cache import Cache
import pytz
import tzlocal
import yaml
from dateutil import tz
from flask import (
    Flask,
    abort,
    jsonify,
    redirect,
    render_template,
    send_file,
    send_from_directory,
)
from flask_frozen import Freezer
from markdown_it import MarkdownIt
from markupsafe import Markup

from utils.zoom_redirect import build_zoom_redirect_url
from utils.shared import (
    SESSION_KINDS,
    calendar_ics_path,
    event_link,
    load_helpdesk_url,
    load_site_config,
    parse_award_nominee,
    parse_conference_dates,
)
from utils.calendar import build_calendar
from utils.session_assignment import parse_file as parse_session_assignment


def chain_functions(*functions: Callable) -> Callable:
    def closure(*args: tuple) -> tuple:
        return reduce(
            lambda acc, func: func(*acc) if isinstance(acc, tuple) else func(acc),
            functions,
            args,
        )

    return closure


AWARD_NOMINEE_CATEGORY = "Award nominee"

site_data = {}
by_uid = {}
timeline = []  # see _build_timeline
award_event_uids = {}  # award session number -> uid of its "Award nominee" event
sponsors = {"dir": "", "tiers": []}  # see docs/SPONSORS.md


def paper_check(row):
    return "paper" in row["type"]


def jobs_check(row):
    return "jobs" in row["type"]


def industry_check(row):
    return "industry" in row["type"]


def music_check(row):
    return "music" in row["type"]


def lbd_check(row):
    return "lbd" in row["type"]


def group_by_days(sdata):
    groups = {}
    for row in sdata["events"]:
        groups[row["day"]] = groups.get(row["day"], []) + [row]

    def f(day, day_events):
        filterbycategory = lambda cat: list(
            filter(lambda x: x["category"] == cat, day_events)
        )
        speakers = filterbycategory("All Meeting")
        posters = filterbycategory("Poster session")
        lbd = filterbycategory("LBD")
        music = filterbycategory("Music")
        industry = filterbycategory("Industry")
        meetup = filterbycategory("Meetup")
        vmeetup = filterbycategory("VMeetup")
        master = filterbycategory("Masterclass")
        wimir = filterbycategory("WiMIR Meetup")
        special = filterbycategory("Meetup-Special")
        opening = filterbycategory("Opening")
        business = filterbycategory("Awards")
        social = filterbycategory("Social")
        tutorials = filterbycategory("Tutorials")
        performances = filterbycategory("Performance")

        out = {
            "uid": day,
            "speakers": speakers,
            "meetup": meetup,
            "special": special,
            "master": master,
            "wimir": wimir,
            "posters": posters,
            "lbd": lbd,
            "music": music,
            "industry": industry,
            "day": day,
            "opening": opening,
            "business": business,
            "social": social,
            "vmeetup": vmeetup,
            "tutorials": tutorials,
            "performances": performances,
        }
        return out

    return [(day, f(day, groups[day])) for day in map(str, range(1, 6))]


def main(site_data_path: str):
    load_dotenv()
    extra_files = ["README.md"]
    # Load all for your sitedata one time.
    for f in glob.glob(site_data_path + "/*"):
        if os.path.isdir(f):
            continue
        extra_files.append(f)
        name, typ = f.split("/")[-1].split(".")
        if name == "main_calendar":
            continue
        if typ == "json":
            site_data[name] = chain_functions(
                open,
                json.load,
            )(f)
        elif typ in {"csv", "tsv"}:
            site_data[name] = chain_functions(
                open,
                csv.DictReader,
                list,
            )(f)
        elif typ == "yml":
            site_data[name] = chain_functions(
                open,
                lambda x: x.read(),
                partial(yaml.load, Loader=yaml.SafeLoader),
            )(f)
    # Enrich before indexing/rendering so live routes and frozen JSON/HTML share
    # the matrix assignments, even when papers.csv contains stale legacy fields.
    _, assignments = parse_session_assignment(site_data_path)
    assignments_by_uid = {paper.uid: paper for paper in assignments}
    missing = [p["uid"] for p in site_data["papers"] if p["uid"] not in assignments_by_uid]
    if missing:
        raise ValueError("Papers missing from session_assignment.csv: " + ", ".join(missing))
    for paper in site_data["papers"]:
        assignment = assignments_by_uid[paper["uid"]]
        # Preserve the CSV string types expected by templates and session filters.
        paper.update(day=str(assignment.day), session=str(assignment.session_index),
                     position=str(assignment.position))

    # TBA: the music and industry sheets still hold ISMIR 2025 data.
    site_data["music"] = []
    site_data["industry"] = []

    for typ in ["papers", "industry", "music", "lbds", "events"]:
        by_uid[typ] = {}
        for p in site_data[typ]:
            by_uid[typ][p["uid"]] = p
    for event in site_data.get("events", []):
        if str(event.get("live_url", "")).strip():
            event["join_url"] = str(event["live_url"]).strip()
            event["zoom_url"] = build_zoom_redirect_url(
                load_site_config(site_data_path)["miniconf_url"],
                str(event["uid"]),
                None,
                include_token=False,
            )

    timeline.clear()
    timeline.extend(_build_timeline(site_data.get("events", [])))
    award_event_uids.clear()
    for event in site_data.get("events", []):
        # "★ Award Nominees\nOral Session - 2"; skips "★ Test of Time Award Talks"
        session = event["title"].split()[-1]
        if event["category"] == AWARD_NOMINEE_CATEGORY and session.isdigit():
            award_event_uids[int(session)] = str(event["uid"])

    openings = [e for e in site_data.get("events", []) if e["category"] == "Opening"]
    app.jinja_env.globals["opening_start_utc"] = (
        min(map(_event_start, openings)).astimezone(pytz.UTC).isoformat() if openings else ""
    )
    music_programs = [e for e in site_data.get("events", []) if e["category"] == "Music"]
    assert len(music_programs) == 1, f"Expected one Music event, got {len(music_programs)}"
    app.jinja_env.globals["music_program_url"] = event_link(music_programs[0])
    industry_programs = [e for e in site_data.get("events", []) if e["category"] == "Industry"]
    assert len(industry_programs) == 1, f"Expected one Industry event, got {len(industry_programs)}"
    app.jinja_env.globals["industry_program_url"] = event_link(industry_programs[0])
    sponsors["dir"] = os.path.abspath(os.path.join(site_data_path, "sponsors"))
    sponsors_yml = os.path.join(sponsors["dir"], "sponsors.yml")
    if os.path.exists(sponsors_yml):
        extra_files.append(sponsors_yml)
        with open(sponsors_yml, encoding="utf-8") as f:
            sponsors["tiers"] = yaml.safe_load(f)
    app.jinja_env.globals["helpdesk_url"] = load_helpdesk_url(site_data_path)
    app.jinja_env.globals["calendar_ics_path"] = calendar_ics_path(site_data_path)

    site_data["main_calendar"] = build_calendar(site_data["events"], site_data["config"])
    site_data["config"]["calendar_days"] = [
        day.isoformat() for day in parse_conference_dates(site_data["config"])
    ]

    site_data.setdefault("config", {})["zoom_redirect_access_token"] = os.environ.get(
        "ZOOM_REDIRECT_ACCESS_TOKEN", ""
    )

    print("Data Successfully Loaded")
    days, events = zip(*group_by_days(site_data))
    site_data["days"] = events
    by_uid["days"] = dict(zip(days, events))

    return extra_files


def _event_start(event):
    timezone = pytz.timezone(_conference_timezone_name())
    naive = datetime.datetime.strptime(  # noqa: DTZ007
        f"{event['start_date']} {event['start_time']}", "%Y-%m-%d %H:%M"
    )
    return timezone.localize(naive)


def _build_timeline(events):
    """Events that have a page, in chronological order (prev/next navigation)."""
    out = []
    for event in sorted(events, key=lambda e: (_event_start(e), _as_int(e["uid"]))):
        url = event_link(event)
        if not url:
            continue
        kind = SESSION_KINDS.get(event["category"])
        out.append({
            "uid": str(event["uid"]),
            "title": str(event["title"]),
            "url": url,
            "session_key": f"{kind}-{event['title'].split()[-1]}" if kind else "",
        })
    return out


# ------------- SERVER CODE -------------------->

app = Flask(__name__)
# cache = Cache(app,config={'CACHE_TYPE': 'simple'})
app.config.from_object(__name__)
freezer = Freezer(app)

markdown_renderer = MarkdownIt("commonmark", {"html": True})


@app.template_filter("markdown")
def markdown_filter(value):
    text = "" if value is None else str(value)
    return Markup(f'<div class="markdown">{markdown_renderer.render(text)}</div>')

# MAIN PAGES


def _data():
    if "config" not in site_data:
        raise RuntimeError(
            "Site data is not initialized. Run the CLI or call main(<data_path>) first."
        )
    data = {}
    data["config"] = site_data["config"]
    return data


def _conference_timezone_name() -> str:
    config = site_data.get("config", {})
    return str(config["timezone"])


def _as_int(value):
    return int(float(str(value)))


def _paper_zoom_url(paper_row):
    day = _as_int(paper_row.get("day"))
    session = _as_int(paper_row.get("session"))
    expected_title = f"Poster Session - {session}"
    for event in site_data.get("events", []):
        if event.get("category") != "Poster session":
            continue
        if _as_int(event.get("day")) != day:
            continue
        if str(event.get("title", "")).strip() != expected_title:
            continue
        return str(event.get("zoom_url", ""))
    return ""


def _award_papers(award_session):
    """Papers of an award session, by position in it."""
    papers = []
    for row in site_data["papers"]:
        award = parse_award_nominee(row["AwardNominee"])
        if award and award[0] == award_session:
            papers.append((award[1], row))
    return [
        {"id": row["uid"], "title": row["title"],
         "session": row["session"], "position": row["position"],
         "authors": remove_affiliation(row["authors_and_affil"])}
        for _, row in sorted(papers, key=lambda p: p[0])
    ]


def _session_links():
    """{"poster"|"oral": {session number: {"channel_url", "zoom_url"}}}"""
    links = {"poster": {}, "oral": {}}
    for event in site_data.get("events", []):
        kind = SESSION_KINDS.get(event.get("category"))
        if kind is None:
            continue
        links[kind][str(event["title"]).split()[-1]] = {
            "channel_url": str(event.get("channel_url") or ""),
            "zoom_url": str(event.get("zoom_url") or ""),
        }
    return links


@app.route("/")
def index():
    return redirect("/calendar.html")


# TOP LEVEL PAGES


@app.route("/index.html")
def home():
    return redirect("/calendar.html")


@app.route("/papers.html")
def papers():
    data = _data()
    data["papers"] = site_data["papers"]
    data["session_links"] = _session_links()
    data["timeline"] = timeline
    return render_template("papers.html", **data)


@app.route("/paper_vis.html")
def paper_vis():
    data = _data()
    return render_template("papers_vis.html", **data)


@app.route("/calendar.html")
def schedule():
    data = _data()
    data["days"] = group_by_days(site_data)
    return render_template("schedule.html", **data)


@app.route("/zoom.html")
def zoom_redirect():
    data = _data()
    data["zoom_targets"] = {
        str(row["uid"]): {
            "uid": str(row["uid"]),
            "title": str(row.get("title", "")),
            "join_url": str(row.get("join_url") or row.get("live_url") or ""),
            "channel_url": str(row.get("channel_url") or ""),
            "slack_channel": str(row.get("slack_channel") or ""),
        }
        for row in site_data.get("events", [])
        if str(row.get("join_url") or row.get("live_url") or "").strip()
    }
    return render_template("zoom.html", **data)


def register_live_route():
    @app.route("/live.html")
    def serve_live():
        live_path = os.path.join(
            os.path.dirname(__file__), "live_overview", "build", "live.html"
        )
        if not os.path.exists(live_path):
            abort(404)
        return send_file(live_path)


@app.route("/tutorials.html")
def tutorials():
    data = _data()
    data["tutorials"] = [t for t in site_data["events"] if t["category"] == "Tutorials"]
    return render_template("tutorials.html", **data)


@app.route("/lbds.html")
def lbds():
    data = _data()
    data["lbds"] = site_data["lbds"]
    return render_template("lbds.html", **data)


@app.route("/lbds_vis.html")
def lbds_vis():
    data = _data()
    return render_template("lbds_vis.html", **data)


@app.route("/special_meetings.html")
def topics():
    data = _data()
    return render_template("special_meetings.html", **data)


# DOWNLOAD CALENDAR


@app.route("/getCalendar")
def get_calendar():
    # Keep this legacy URL extensionless for compatibility.
    # Use octet-stream so Frozen-Flask's guessed type for extensionless
    # paths matches the served Content-Type during static builds.
    return send_file(
        app.jinja_env.globals["calendar_ics_path"],
        as_attachment=True,
        mimetype="application/octet-stream",
    )


def extract_list_field(v, key):
    value = v.get(key, "")
    if isinstance(value, list):
        return value
    else:
        # remove starting and trailing spaces, captalize first letter of each term
        toCap = lambda s: s[:1].upper() + s[1:] if s else s
        return [
            toCap(x.strip()) for x in sum([x.split("->") for x in value.split(";")], [])  # noqa: RUF017 because O(1)
        ]


def remove_nested_parens_and_braces(s: str) -> str:
    # remove innermost (...) or {...} (and optional trailing '*') repeatedly
    while True:
        new = re.sub(r"\s*(\([^()]*\)|\{[^{}]*\})\*?", "", s)
        if new == s:
            return new
        s = new


def remove_affiliation(s):
    clean = remove_nested_parens_and_braces(s)
    # replace more than one space with single space
    clean = re.sub(r"\s+", " ", clean)
    clean = clean.replace(",", ";")
    names = [n.strip() for n in clean.split(";") if n.strip()]
    return names


def convert_drive_link(s):
    if "drive.google.com" in s:
        # extract id from url, which has "id=" and maybe "&"
        match = re.search(r"id=([^&]+)", s)
        if match:
            file_id = match.group(1)
            s = f"https://drive.google.com/file/d/{file_id}/preview"
    return s


def paper_thumbnail_path(v) -> str:
    # URL -> filename map written by scripts/download_paper_thumbnails.py
    try:
        with open("static/paper_images/url_map.json", encoding="utf-8") as f:
            url_map = json.load(f)
    except FileNotFoundError:
        return ""
    # Papers: raw_thumbnail (mock: thumbnail); LBDs: raw_thumbnail_path.
    url = (v.get("raw_thumbnail") or v.get("raw_thumbnail_path") or v.get("thumbnail") or "").strip()
    return f"static/paper_images/{url_map[url]}" if url in url_map else ""


def get_yt_id(yt_link: str) -> str:
    if not yt_link:
        return ""
    url = urlparse(yt_link.strip())
    video_id = ""
    if url.hostname in {"youtube.com", "www.youtube.com", "m.youtube.com"}:
        if url.path == "/watch":
            video_id = parse_qs(url.query).get("v", [""])[0]
        elif url.path.startswith("/embed/"):
            video_id = url.path.removeprefix("/embed/")
    elif url.hostname == "youtu.be":
        video_id = url.path.removeprefix("/")
    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", video_id):
        return video_id
    raise ValueError(f"Invalid YouTube URL: {yt_link!r}")


def format_paper(v):
    list_keys = [
        "authors",
        "primary_subject",
        "secondary_subject",
        "session",
        "authors_and_affil",
    ]
    list_fields = {k: extract_list_field(v, k) for k in list_keys}
    award = parse_award_nominee(v["AwardNominee"])

    process = lambda s: s.replace("\n ", "\n")

    reviews = {
        k: process(v.get(k, ""))
        for k in [
            "review1",
            "review2",
            "review3",
            "review4",
            "meta_review",
            "publish_reviews",
        ]
    }
    return {
        "id": v["uid"],
        "session": v["session"],
        "position": v["position"],
        "forum": v["uid"],
        "content": {
            "title": v["title"],
            "summary_of_updates_post_review": v.get(
                "summary_of_updates_post_review", ""
            ),
            "paper_presentation": v["paper_presentation"],
            "award_session": award[0] if award else None,
            "authors": remove_affiliation(v["authors_and_affil"]),
            "authors_and_affil": list_fields["authors_and_affil"],
            "keywords": list(
                set(
                    list_fields["primary_subject"]
                    + list_fields["secondary_subject"]
                    + (["TISMIR"] if v["is_tismir"] in {"TRUE", "Yes"} else [])
                    + (["Awards Nominee"] if award else [])
                    + (["Open Review"] if v["publish_reviews"] in {"TRUE", "Yes"} else [])
                )
            ),
            "abstract": v["abstract"]
            # + '<br><br> <b><p align="center">[Direct link to video]({})</b>'.format(
            #     v["video"]
            # )
            ,
            "TLDR": v["abstract"],
            "session": list_fields["session"],
            "pdf_path": convert_drive_link(v.get("raw_pdf_path", "")),
            "poster_pdf": convert_drive_link(v.get("raw_poster_pdf", "")),
            "slides": convert_drive_link(v.get("raw_slides_pdf", "")),
            "thumbnail": paper_thumbnail_path(v),
            "video": get_yt_id(v.get("video") or ""),
            "channel_url": v["channel_url"],
            "slack_channel": v["slack_channel"],
            "day": v["day"],
        },
        "poster_pdf": "GLTR_poster.pdf",
        "reviews": reviews,
    }


def lbd_group_channel(v):
    """The Slack channel of the LBD's topic group (lbds_grouping.csv: group_id, slack_channel, channel_url)."""
    group = str(v.get("group_id", "")).strip()
    row = next((r for r in site_data.get("lbds_grouping", []) if str(r.get("group_id", "")).strip() == group), None) if group else None
    url = str((row or {}).get("channel_url", "")).strip()
    if not url.startswith("https://"):
        return "", ""
    return str(row.get("slack_channel", "")).strip().lstrip("#"), url


# The real LBD sheet's author columns, best first: the authors as printed in the PDF, then as
# entered in CMT (LBDs without a PDF have only that), then the papers' column name.
LBD_AUTHOR_COLUMNS = ("authors_and_affil_from_pdf", "authors_and_affil_from_cmt", "authors_and_affil")


def format_lbd(v):
    """One LBD for the templates.

    The real LBD sheet has the papers' columns (authors in LBD_AUTHOR_COLUMNS, raw_pdf_path,
    raw_poster_pdf, video_path, key_words, slack_channel); the mock one has its own (authors as
    "Last, First", paper_link, poster_link, youtube_id, primary_subject, channel_name). Both are read.
    """
    authors_and_affil = next((v[c] for c in LBD_AUTHOR_COLUMNS if v.get(c, "").strip()), "")
    if authors_and_affil:
        # Names only: no affiliations, no "*" (the corresponding author's mark).
        authors = [n for n in (a.replace("*", "").strip() for a in remove_affiliation(authors_and_affil)) if n]
    else:
        authors = [
            (
                " ".join(reversed(x.replace(" ", "").replace("*", "").split(",")))
                if "," in x
                else x.replace("*", "")
            )
            for x in extract_list_field(v, "authors")
        ]
    if "key_words" in v:
        keywords = [k.strip() for k in re.split(r"[,;\n]", v["key_words"]) if k.strip() and k.strip() != "[Not Answered]"]
    else:
        keywords = extract_list_field(v, "primary_subject")
    if v.get("video_path", "").strip():
        youtube_id = f"https://www.youtube.com/embed/{get_yt_id(v['video_path'])}"
    else:
        youtube_id = v.get("youtube_id", "")
        if youtube_id and not youtube_id.startswith(("http://", "https://")):
            youtube_id = f"https://www.youtube.com/embed/{youtube_id}"
    return {
        "id": v["uid"],
        "position": v.get("position", ""),
        "forum": v["uid"],
        "content": {
            "title": v["title"],
            "authors": authors,
            "abstract": v["abstract"],
            "TLDR": v["abstract"],
            "session": extract_list_field(v, "session") if v.get("session", "").strip() else [],
            # Downloaded like the papers' (real sheet); the mock sheet names a static image.
            "thumbnail": paper_thumbnail_path(v) or v.get("thumbnail_link", ""),
            "poster_link": convert_drive_link(v.get("raw_poster_pdf") or v.get("poster_link", "")),
            "paper_link": convert_drive_link(v.get("raw_pdf_path") or v.get("paper_link", "")),
            "poster_type": v.get("poster_type", ""),
            "bilibili_id": v.get("bilibili_id", ""),
            "youtube_id": convert_drive_link(youtube_id),
            "channel_url": v.get("channel_url", ""),
            "channel_name": v.get("slack_channel") or v.get("channel_name", ""),
            "group_channel_name": lbd_group_channel(v)[0],
            "group_channel_url": lbd_group_channel(v)[1],
            # As the papers' paper_presentation: "Virtual" / "In-person", '' when not known yet.
            "presentation_mode": "" if v.get("presentation_mode", "").strip() == "[Not Answered]"
            else v.get("presentation_mode", "").strip().replace("In-Person", "In-person"),
            "day": 4,
            "keywords": keywords,
        },
    }


def format_workshop(v):
    list_keys = ["authors"]
    list_fields = {}
    for key in list_keys:
        list_fields[key] = extract_list_field(v, key)

    return {
        "id": v["uid"],
        "title": v["title"],
        "organizers": list_fields["authors"],
        "abstract": v["abstract"],
    }


def format_music(v):
    return {
        "id": v["uid"],
        "content": {
            "title": v["title"],
            "authors": v["authors"],
            "affiliation": v["affiliation"],
            "abstract": v["abstract"],
            "bio": v["bio"],
            "web_link": v["web_link"],
            "session": v["session"],
            "yt_id": v["yt_id"],
            "bb_id": v["bb_id"],
        },
    }


def format_jobs(v):
    return {
        "id": v["uid"],
        "content": {
            "title": v["title"],
            "jd": v["jd"],
            "channel_name": v["channel_name"],
            "channel_url": v["channel_url"],
            "company": v["company"],
            "external_web_link": v["external_web_link"],
        },
    }


def format_industry(v):
    return {
        "id": v["uid"],
        "content": {
            "title": v["title"],
            "session": v["session"],
            "channel_name": v["channel_name"],
            "channel_url": v["channel_url"],
            "company": v["company"],
        },
    }


@app.template_filter("localcheck")
def datetimelocalcheck(s):
    return tzlocal.get_localzone()


@app.template_filter("localizetime")
def localizetime(date, time, timezone):
    to_zone = tz.gettz(str(timezone))
    from_zone_name = _conference_timezone_name()
    from_zone = pytz.timezone(from_zone_name)
    naive_date = datetime.datetime.strptime(date + " " + time, "%Y-%m-%d %H:%M")  # noqa: DTZ007
    ref_date_tz = from_zone.localize(naive_date)
    local_date = ref_date_tz.astimezone(to_zone) if to_zone else ref_date_tz
    return local_date.strftime("%Y-%m-%d"), local_date.strftime("%H:%M")


# ITEM PAGES


@app.route("/day_<day>.html")
def day(day):
    uid = day
    v = by_uid["days"][uid]
    data = _data()
    data["day"] = v
    data["daynum"] = uid
    return render_template("day.html", **data)


@app.route("/poster_<poster>.html")
def poster(poster):
    uid = poster
    v = by_uid["papers"][uid]
    data = _data()
    paper_data = format_paper(v)
    paper_data["zoom_url"] = _paper_zoom_url(v)
    award_event_uid = award_event_uids.get(paper_data["content"]["award_session"])
    paper_data["award_url"] = (
        event_link(by_uid["events"][award_event_uid]) if award_event_uid else ""
    )
    data["paper"] = paper_data
    return render_template("poster.html", **data)


@app.route("/event_<slug>.html")
def event(slug):
    url = f"event_{slug}.html"
    index = next((i for i, e in enumerate(timeline) if e["url"] == url), None)
    if index is None:
        abort(404)
    event = timeline[index]["uid"]
    v = by_uid["events"][event]
    start = _event_start(v)
    data = _data()
    data["event"] = v
    award_session = next(
        (s for s, uid in award_event_uids.items() if uid == event), None
    )
    data["award_papers"] = _award_papers(award_session) if award_session else []
    data["sponsor_tiers"] = sponsors["tiers"] if v["category"] == "Industry" else []
    data["start_label"] = start.strftime("%a, %b %-d, %H:%M")
    data["start_utc"] = start.astimezone(pytz.UTC).isoformat()
    data["timezone_name"] = _conference_timezone_name()
    data["prev_event"] = timeline[index - 1] if index else None
    data["next_event"] = timeline[index + 1] if index + 1 < len(timeline) else None
    return render_template("event.html", **data)


# Disabled: `speakers` data is not loaded into by_uid, so this route is currently
# unimplemented and breaks static freezing/runtime if linked.
# @app.route("/speaker_<speaker>.html")
# def speaker(speaker):
#     uid = speaker
#     v = by_uid["speakers"][uid]
#     data = _data()
#     data["speaker"] = v
#     return render_template("speaker.html", **data)


# Disabled: `workshops` data is not loaded into by_uid, so this route is currently
# unimplemented and breaks static freezing/runtime if linked.
# @app.route("/workshop_<workshop>.html")
# def workshop(workshop):
#     uid = workshop
#     v = by_uid["workshops"][uid]
#     data = _data()
#     data["workshop"] = format_workshop(v)
#     return render_template("workshop.html", **data)


@app.route("/music_<music>.html")
def music(music):
    uid = music
    v = by_uid["music"][uid]
    data = _data()
    data["music"] = v
    return render_template("piece.html", **data)


# Disabled: `jobs` data is not loaded into by_uid, so this route is currently
# unimplemented and breaks static freezing/runtime if linked.
# @app.route("/jobs_<jobs>.html")
# def jobs(jobs):
#     uid = jobs
#     v = by_uid["jobs"][uid]
#     data = _data()
#     data["jobs"] = v
#     return render_template("jobs_template.html", **data)


@app.route("/industry_<industry>.html")
def industry(industry):
    uid = industry
    v = by_uid["industry"][uid]

    v = v.copy()
    v["video"] = get_yt_id(v.get("video", ""))
    v["video2"] = get_yt_id(v.get("video2", ""))

    data = _data()
    data["industry"] = v
    return render_template("company.html", **data)


@app.route("/lbd_<lbd>.html")
def lbd(lbd):
    uid = lbd
    v = by_uid["lbds"][uid]
    data = _data()
    data["lbd"] = format_lbd(v)
    return render_template("lbd.html", **data)


# FRONT END SERVING


@app.route("/papers.json")
def paper_json():
    json = []
    for v in site_data["papers"]:
        json.append(format_paper(v))
    return jsonify(json)


@app.route("/lbds.json")
def lbds_json():
    json = [format_lbd(v) for v in site_data["lbds"]]
    return jsonify(json)


@app.route("/static/<path:path>")
def send_static(path):
    if "wo_num" in path:
        abort(404)
    return send_from_directory("static", path)


@app.route("/sponsors/<path:path>")
def send_sponsor_logo(path):
    return send_from_directory(sponsors["dir"], path)


@app.route("/serve_<path>.json")
def serve(path):
    if path == "events":
        abort(404)
    return jsonify(site_data[path])


# --------------- DRIVER CODE -------------------------->
# Code to turn it all static


@freezer.register_generator
def generator():

    yield "zoom_redirect", {}

    for paper in site_data["papers"]:
        yield "poster", {"poster": str(paper["uid"])}
    for music in site_data["music"]:
        yield "music", {"music": str(music["uid"])}
    for industry in site_data["industry"]:
        yield "industry", {"industry": str(industry["uid"])}
    for lbd in site_data["lbds"]:
        yield "lbd", {"lbd": str(lbd["uid"])}
    for event in timeline:
        if event["url"].startswith("event_"):
            yield "event", {"slug": event["url"][len("event_"):-len(".html")]}
    for day in site_data["days"]:
        yield "day", {"day": str(day["uid"])}

    for key in site_data:
        if key not in {"days", "events"}:
            yield "serve", {"path": key}

    for tier in sponsors["tiers"]:
        for sponsor in tier["sponsors"]:
            yield "send_sponsor_logo", {"path": sponsor["logo"]}

    # Freeze explicit paths for the dynamic /static/<path:path> route.
    static_root = app.static_folder or "static"
    for root, _, files in os.walk(static_root):
        for filename in files:
            rel_path = os.path.relpath(os.path.join(root, filename), static_root)
            rel_path = rel_path.replace(os.sep, "/")
            if "wo_num" in rel_path:
                continue
            yield "send_static", {"path": rel_path}


def parse_arguments():
    parser = argparse.ArgumentParser(description="MiniConf Portal Command Line")

    parser.add_argument(
        "--build",
        action="store_true",
        default=False,
        help="Convert the site to static assets",
    )

    parser.add_argument(
        "-b",
        action="store_true",
        default=False,
        dest="build",
        help="Convert the site to static assets",
    )

    parser.add_argument(
        "--dev", action="store_true",
        help="Dev build: alert on missing data instead of silently hiding it",
    )

    parser.add_argument(
        "--mockup", action="store_true",
        help="Use sitedata_mock instead of sitedata",
    )

    args = parser.parse_args()
    return args


if __name__ == "__main__":
    args = parse_arguments()
    data_path = "sitedata_mock" if args.mockup else "sitedata"

    extra_files = main(data_path)
    app.jinja_env.globals["dev_build"] = args.dev
    if args.build:
        freezer.freeze()
    else:
        register_live_route()
        debug_val = False
        if os.getenv("FLASK_DEBUG") == "True":
            debug_val = True
        app.run(host="0.0.0.0", port=10000, debug=debug_val, extra_files=extra_files)
