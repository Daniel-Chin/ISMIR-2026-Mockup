import os
import re

import pandas as pd

from utils.session_assignment import parse_file


class ZoomCreator:
    """
    Creates Zoom meetings for the live sessions in the events CSV and writes the
    join URLs back into its live_url column (via utils/zoom.py). Poster sessions
    get one pre-created breakout room per poster, named after the paper's Slack
    channel, so the poster craze can split into per-paper rooms.
    """

    # Tutorials are created manually; the other skipped categories need no call.
    SKIP_CATEGORIES = ("Tutorials", "Social", "Registration", "Majlis", "Lunch")

    POSTER_SESSION_RE = re.compile(r"Poster Session - (\d+)")

    def __init__(self, eventsCsvFile, useDummyValues=True, papersCsvFile=None, topicPrefix=""):
        self.eventsCsvFile = eventsCsvFile
        self.topicPrefix = topicPrefix
        self.useDummyValues = useDummyValues
        self.papers = pd.read_csv(papersCsvFile, dtype={"uid": str}) if papersCsvFile else None
        if self.papers is not None:
            _, papers = parse_file(os.path.dirname(os.fspath(papersCsvFile)) or ".")
            assignments = {paper.uid: paper for paper in papers}
            missing = [uid for uid in self.papers.uid if uid not in assignments]
            if missing:
                raise ValueError(
                    "Papers missing from session_assignment.csv: " + ", ".join(missing)
                )
            for column, attribute in (("day", "day"), ("session", "session_index"),
                                      ("position", "position")):
                self.papers[column] = self.papers.uid.map(
                    lambda uid: getattr(assignments[uid], attribute)
                )

    def _wantsZoom(self, row):
        return row["category"] not in self.SKIP_CATEGORIES

    def _breakoutRooms(self, row):
        """Room names (paper Slack channels) for a 'Poster Session - N' row, else None."""
        if self.papers is None:
            return None
        match = self.POSTER_SESSION_RE.match(str(row["title"]))
        if not match:
            return None
        sessionPapers = self.papers[
            # Session indices are conference-wide. Assignment days start at
            # the first paper session; event days can include tutorials before it.
            self.papers.session == int(match.group(1))
        ].sort_values("position")
        rooms = [str(ch) for ch in sessionPapers.slack_channel.dropna()]
        return rooms or None

    def setupZoomCalls(self, zoomUtils, passcode=None):
        if self.eventsCsvFile is None:
            raise Exception("eventsCsvFile passed in constructor is null")

        csv_data = pd.read_csv(self.eventsCsvFile)
        if self.useDummyValues:
            self._printZoomPlan(csv_data, zoomUtils)
            return

        wanted = csv_data[csv_data.apply(self._wantsZoom, axis=1)]

        print("## Number of items to create zoom link for: ", len(wanted.index))
        print("### Final data: ", wanted[["uid", "title", "category"]])
        for _, row in wanted.iterrows():
            rooms = self._breakoutRooms(row)
            if rooms:
                print(f"### Breakout rooms for '{row['title']}': {rooms}")

        zoomUtils.createZoomLinksIfNeeded(
            self.eventsCsvFile,
            "title",
            "live_url",
            "uid",
            rowFilter=self._wantsZoom,
            breakoutRoomsForRow=self._breakoutRooms,
            passcode=passcode,
            topicPrefix=self.topicPrefix,
        )

    def _printZoomPlan(self, csv_data, zoomUtils):
        entities = {}
        assignments = []
        for _, row in csv_data.iterrows():
            codename = None
            if self._wantsZoom(row):
                rooms = self._breakoutRooms(row)
                if zoomUtils._isPosterSessionRow(row, rooms):
                    # Production reuses poster meetings by their exact title.
                    key = ("Meeting", self.topicPrefix + row["title"])
                    codename = entities.get(key, {}).get("codename")
                    if codename is None:
                        poster_number = 1 + sum(kind == "Meeting" for kind, _ in entities)
                        codename = f"poster-{poster_number}"
                        entities[key] = {"codename": codename, "rooms": rooms or []}
                else:
                    key = ("Webinar", self.topicPrefix + zoomUtils._sharedWebinarTopic(self.eventsCsvFile))
                    codename = "shared-webinar"
                    entities[key] = {"codename": codename, "rooms": []}
            assignments.append((row, codename))

        print("## Dummy mode (no --prod true): no Zoom API calls made.")
        print(f"## Zoom entities to create or reuse: {len(entities)} "
              f"({sum(kind == 'Webinar' for kind, _ in entities)} webinar(s), "
              f"{sum(kind == 'Meeting' for kind, _ in entities)} meeting(s))")
        print("Existing Zoom entities are not checked; actual creation count may be lower.")
        print("Codenames are local plan labels, not Zoom IDs.")
        print("### Entities: codename | type | topic | breakout rooms")
        for (kind, topic), entity in entities.items():
            print(f"{entity['codename']} | {kind} | {topic} | {len(entity['rooms'])}")
            for room in entity["rooms"]:
                print(f"  Breakout room: {room}")
        print()
        print("### Event assignments: uid | codename | title | category")
        for row, codename in assignments:
            title = " ".join(str(row["title"]).split())
            print(f"{row['uid']} | {codename} | {title} | {row['category']}")


# Tutorials run 3 in parallel; each parallel slot uses its own webinar license.
TUTORIAL_ACCOUNT_SUFFIXES = ("", "_2", "_3")
# Extra accounts may not offer webinar read scopes, so created webinars are
# remembered here (topic -> id, account, join_url) instead of listed from Zoom.
TUTORIAL_WEBINARS_STATE = "local/zoom_tutorial_webinars.json"


def setupTutorialWebinars(eventsCsvFile, zoomUtils, useDummyValues=True,
                          passcode=None, topicPrefix=""):
    """One webinar per tutorial, on the account of its parallel slot. Prints
    title + join URL; never writes events.csv. Create-once: webinars already in
    TUTORIAL_WEBINARS_STATE are reprinted, not touched. Needs only write scope."""
    import json

    state = {}
    if os.path.exists(TUTORIAL_WEBINARS_STATE):
        with open(TUTORIAL_WEBINARS_STATE) as f:
            state = json.load(f)
    events = pd.read_csv(eventsCsvFile)
    tutorials = events[events.category == "Tutorials"]
    timezone = zoomUtils._load_conference_timezone(eventsCsvFile)
    for _, slot in tutorials.groupby(["start_date", "start_time"], sort=False):
        if len(slot) > len(TUTORIAL_ACCOUNT_SUFFIXES):
            raise ValueError(f"{len(slot)} parallel tutorials but only "
                             f"{len(TUTORIAL_ACCOUNT_SUFFIXES)} Zoom accounts")
        for suffix, (_, row) in zip(TUTORIAL_ACCOUNT_SUFFIXES, slot.iterrows()):
            topic = topicPrefix + row["title"]
            hh, mm = str(row["start_time"]).split(":")
            startTime = f"{row['start_date']}T{int(hh):02d}:{mm}:00"
            duration = zoomUtils._durationMinutes(row)
            account = f"ZOOM_API_*{suffix or ' (main)'}"
            if topic in state:
                print(f"{topic}\n  (existing) {state[topic]['account']}: {state[topic]['join_url']}")
                continue
            if useDummyValues:
                print(f"[dry-run] {account}: {topic} @ {startTime} {timezone} ({duration} min)")
                continue
            zoomUtils.useAccount(suffix)
            webinar = zoomUtils.createWebinar(topic, startTime, duration,
                                              timezone=timezone, passcode=passcode)
            state[topic] = {"id": webinar["id"], "account": account,
                            "join_url": webinar["join_url"]}
            os.makedirs(os.path.dirname(TUTORIAL_WEBINARS_STATE), exist_ok=True)
            with open(TUTORIAL_WEBINARS_STATE, "w") as f:
                json.dump(state, f, indent=2)
            print(f"{topic}\n  {account}: {webinar['join_url']}")
    zoomUtils.useAccount("")
