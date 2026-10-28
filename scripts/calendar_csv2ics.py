from datetime import datetime, timedelta
import os

import pandas as pd
import pytz
from icalendar import Calendar, Event

from utils.shared import (
    calendar_ics_path,
    event_link,
    load_conference_timezone_name,
    load_site_config,
)

from utils.zoom_redirect import build_zoom_redirect_url


def load_conference_timezone(in_csv):
    timezone = load_conference_timezone_name(
        os.path.dirname(in_csv), 
    )
    return pytz.timezone(timezone)


def make_dt(conf_tz, year, month, day, hour=0, minute=0, second=0):
    """Create a timezone-aware datetime: localize to conference tz then convert to UTC."""
    local = datetime(year, month, day, hour, minute, second)
    local = conf_tz.localize(local)  # properly attach pytz tzinfo
    return local.astimezone(pytz.UTC)  # convert to UTC for ICS (Z times)


def display(cal):
    return cal.to_ical().replace("\r\n", "\n").strip()


def toDescription(site_data_path, event):
    miniconf_prefix = "Miniconf page: "
    miniconf_url = load_site_config(site_data_path)["miniconf_url"]
    if event["category"] in [
        "Poster session", 
        "Oral session", 
    ]:
        session_num = event["title"].split()[-1]
        rel_link = f"papers.html?session={session_num}"
    elif event["category"] == "LBD":
        rel_link = "lbds.html"
    elif event["category"] == "Tutorials":
        rel_link = "tutorials.html"
    elif event["category"] in ["Industry", "Music"]:
        rel_link = event_link(event)
    elif event["category"] == "Satellite":
        rel_link = event["web_link"]
    else:
        rel_link = ""

    miniconf_des = (
        miniconf_prefix + miniconf_url.rstrip("/") + "/" + rel_link
        if rel_link
        else ""
    )

    slack_link = (
        f"Slack channel: {event['channel_url']}"
        if not pd.isna(event["channel_url"])
        else ""
    )
    livestream_link = (
        f"Zoom: {build_zoom_redirect_url(miniconf_url, event['uid'], None, False)}"
        if not pd.isna(event["live_url"])
        else ""
    )

    return "\n".join(filter(None, [miniconf_des, slack_link, livestream_link]))


def calendar_csv2ics(in_csv="sitedata/events.csv", out_ics=None):
    conf_tz = load_conference_timezone(in_csv)
    site_data_path = os.path.dirname(in_csv)
    conf_name = load_site_config(site_data_path)["name"]
    if out_ics is None:
        out_ics = calendar_ics_path(site_data_path)
    orig_csv = pd.read_csv(in_csv)
    orig_csv = orig_csv.sort_values(by=["uid"])

    cal = Calendar()
    cal.add("prodid", f"{conf_name} calendar")
    cal.add("version", "2.0")

    tut_csv = orig_csv.copy()[orig_csv["category"].isin(["Tutorials"])]
    tut_csv = tut_csv.sort_values(by=["title"])

    for index, event in orig_csv.iterrows():
        e_cal = Event()
        if pd.isna(event["title"]):
            continue
        e_date = [int(x) for x in event["start_date"].split("-")]
        e_start_time = [int(x) for x in event["start_time"].split(":")]
        e_end_time = (
            None
            if str(event["end_time"]).strip().lower() == "tbd"
            else [int(x) for x in event["end_time"].split(":")]
        )
        # make uid a string and add a domain to be a valid UID
        e_cal.add("uid", f"{int(event['uid'])}@{conf_name.replace(' ', '').lower()}virtual")
        # use current UTC time for dtstamp
        e_cal.add("dtstamp", datetime.now(pytz.UTC))

        # No LOCATION: the miniconf link is already in the description.
        e_cal["description"] = toDescription(
            os.path.normpath(os.path.join(in_csv, "..")),
            event, 
        )

        e_cal.add("summary", " ".join(event["title"].split()))
        # build dtstart/dtend as UTC-aware datetimes
        e_cal.add(
            "dtstart",
            make_dt(
                conf_tz,
                e_date[0],
                e_date[1],
                e_date[2],
                e_start_time[0],
                e_start_time[1],
                0,
            ),
        )

        if e_end_time is None:
            # Unknown end times use a two-hour duration, even across midnight.
            e_cal.add("dtend", e_cal.decoded("dtstart") + timedelta(hours=2))
        elif e_end_time[0] < e_start_time[0]:
            e_cal.add(
                "dtend",
                make_dt(
                    conf_tz,
                    e_date[0],
                    e_date[1],
                    e_date[2] + 1,
                    e_end_time[0],
                    e_end_time[1],
                    0,
                ),
            )
        else:
            e_cal.add(
                "dtend",
                make_dt(
                    conf_tz,
                    e_date[0],
                    e_date[1],
                    e_date[2],
                    e_end_time[0],
                    e_end_time[1],
                    0,
                ),
            )

        cal.add_component(e_cal)

    with open(out_ics, "wb") as f:
        print("Updated calendar ICS file")
        f.write(cal.to_ical())


if __name__ == "__main__":
    calendar_csv2ics()
