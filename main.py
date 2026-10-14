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
    calendar_ics_path,
    load_helpdesk_url,
    load_site_config,
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


site_data = {}
by_uid = {}


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


# ------------- SERVER CODE -------------------->

app = Flask(__name__)
# cache = Cache(app,config={'CACHE_TYPE': 'simple'})
app.config.from_object(__name__)
freezer = Freezer(app)

markdown_renderer = MarkdownIt("commonmark", {"html": True})


@app.template_filter("markdown")
def markdown_filter(value):
    text = "" if value is None else str(value)
    return Markup(markdown_renderer.render(text))

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


def _session_links():
    """{"poster"|"oral": {session number: {"channel_url", "zoom_url"}}}"""
    links = {"poster": {}, "oral": {}}
    for event in site_data.get("events", []):
        kind = {"Poster session": "poster", "Oral session": "oral"}.get(event.get("category"))
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
    return render_template("papers.html", **data)


@app.route("/paper_vis.html")
def paper_vis():
    data = _data()
    return render_template("papers_vis.html", **data)


@app.route("/calendar.html")
def schedule():
    data = _data()
    data["days"] = group_by_days(site_data)
    data["construction_notice"] = (
        "Site under construction. \nIf you are an organizer, you are welcome to test "
        "the website! \nIf you are a visitor who got here by guessing the domain name, "
        "well, congrats on finding the ISMIR2026 miniconf! But know that conference materials are still being linked up. "
        "Watch out for pre-conference announcements!"
    )
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


@app.route("/music.html")
def musics():
    data = _data()
    data["music"] = site_data["music"]
    return render_template("music.html", **data)


@app.route("/industry.html")
def industries():
    data = _data()
    data["industry"] = site_data["industry"]
    return render_template("industry.html", **data)


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
    url = (v.get("raw_thumbnail") or v.get("thumbnail") or "").strip()
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
            "long_presentation": v["long_presentation"],
            "authors": remove_affiliation(v["authors_and_affil"]),
            "authors_and_affil": list_fields["authors_and_affil"],
            "keywords": list(
                set(
                    list_fields["primary_subject"]
                    + list_fields["secondary_subject"]
                    + (["TISMIR"] if v["is_tismir"] in {"TRUE", "Yes"} else [])
                    + (["Awards Nominee"] if v["AwardNominee"] in {"TRUE", "Yes"} else [])
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


def format_lbd(v):
    list_keys = ["authors", "session", "primary_subject"]
    list_fields = {k: extract_list_field(v, k) for k in list_keys}
    youtube_id = v.get("youtube_id", "")
    if youtube_id and not youtube_id.startswith(("http://", "https://")):
        youtube_id = f"https://www.youtube.com/embed/{youtube_id}"
    return {
        "id": v["uid"],
        "position": v["position"],
        "forum": v["uid"],
        "content": {
            "title": v["title"],
            "authors": [
                (
                    " ".join(reversed(x.replace(" ", "").replace("*", "").split(",")))
                    if "," in x
                    else x.replace("*", "")
                )
                for x in list_fields["authors"]
            ],
            "abstract": v["abstract"],
            "TLDR": v["abstract"],
            "session": list_fields["session"],
            "thumbnail_link": v.get("thumbnail_link", ""),
            "poster_link": convert_drive_link(v.get("poster_link", "")),
            "paper_link": convert_drive_link(v.get("paper_link", "")),
            "poster_type": v.get("poster_type", ""),
            "bilibili_id": v.get("bilibili_id", ""),
            "youtube_id": convert_drive_link(youtube_id),
            "day": 4,
            "keywords": list_fields["primary_subject"],
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
    data["paper"] = paper_data
    return render_template("poster.html", **data)


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


@app.route("/chat.html")
def chat():
    data = _data()
    return render_template("chat.html", **data)


# FRONT END SERVING


@app.route("/papers.json")
def paper_json():
    json = []
    for v in site_data["papers"]:
        json.append(format_paper(v))
    return jsonify(json)


@app.route("/music.json")
def music_json():
    json = [*site_data["music"]]
    return jsonify(json)


@app.route("/industry.json")
def industry_json():
    json = [*site_data["industry"]]
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
    for day in site_data["days"]:
        yield "day", {"day": str(day["uid"])}

    for key in site_data:
        if key not in {"days", "events"}:
            yield "serve", {"path": key}

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
