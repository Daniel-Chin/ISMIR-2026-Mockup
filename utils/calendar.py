"""Convert loaded events.csv rows into the website calendar's schedule format."""

from datetime import datetime, timedelta

import pytz

SESSION_KINDS = {"Poster session": "poster", "Oral session": "oral"}
NO_PAGE_CATEGORIES = {"Registration", "Lunch"}


def event_link(event):
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


def build_calendar(events, config):
    timezone = pytz.timezone(config["timezone"])
    schedules = []
    for event in events:
        if not event["title"].strip():
            continue
        start = datetime.strptime(
            f"{event['start_date']} {event['start_time']}", "%Y-%m-%d %H:%M"
        )
        end_time_tbd = event["end_time"].strip().lower() == "tbd"
        if end_time_tbd:
            end = timezone.localize(start) + timedelta(hours=3)
        else:
            end = datetime.strptime(
                f"{event['start_date']} {event['end_time']}", "%Y-%m-%d %H:%M"
            )
            if end < start:
                end += timedelta(days=1)
            end = timezone.localize(end)

        link = event_link(event)

        description = []
        if link:
            page_url = link if link.startswith(("https://", "http://")) else (
                config["miniconf_url"].rstrip("/") + "/" + link
            )
            description.append(f"Miniconf page: {page_url}")
        if event.get("channel_url"):
            description.append(f"Slack channel: {event['channel_url']}")
        if event.get("zoom_url"):
            description.append(f"Zoom: {event['zoom_url']}")
        schedules.append({
            "title": event["title"],
            "start": timezone.localize(start).astimezone(pytz.UTC).isoformat(),
            "end": end.astimezone(pytz.UTC).isoformat(),
            "location": link,
            "link": link,
            "category": "time",
            "calendarId": event["category"].replace(" ", "_"),
            "scrollKey": "\n".join(description),
            "raw": {"endTimeTbd": end_time_tbd},
        })
    return schedules
