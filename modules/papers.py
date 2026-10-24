import re
import os

import pandas as pd
from tqdm import tqdm

from utils import slack as slackUtils
from utils.shared import load_conference_timezone_name, load_site_config
from utils.session_assignment import parse_file


def title2channelID(
    title: str,
    paper_id = None,
    session_number: int | None = None,
    paper_number: int | None = None,
) -> str:
    if session_number is not None and paper_number is not None:
        prefix = f"p{session_number}-{paper_number}"
    else:
        prefix = f"p{paper_id}"

    return slackUtils.build_channel_name(prefix, title)


# Defining the class that exposes the methods related to papaers.
class Papers:
    """
    This method takes the config data loaded and the papers csv file.
    """

    def __init__(self, data_path, papersCsvFile, useDummyValues, eventsCsvFile=None):
        self.data_path = data_path
        self.papersCsvFile = papersCsvFile
        self.useDummyValues = useDummyValues
        self.eventsCsvFile = eventsCsvFile
        data_dir = (
            os.path.dirname(self.papersCsvFile) if self.papersCsvFile else "sitedata"
        )
        self.conference_timezone = load_conference_timezone_name(data_dir)

    def _paper_assignments(self, csv_data):
        _, papers = parse_file(self.data_path)
        assignments = {paper.uid: paper for paper in papers}
        missing = [uid for uid in csv_data["uid"] if uid not in assignments]
        if missing:
            raise ValueError(
                "Papers missing from session_assignment.csv: " + ", ".join(missing)
            )
        return assignments

    """
    This method inputs the zoomUtils and setup zoom calls for the all the sessions.
    """

    def setupSlackChannels(self, *_):
        if self.papersCsvFile is None:
            raise Exception("self.papersCsvFile passed in contructor is null")

        # Reading the papers data.
        csv_data = pd.read_csv(self.papersCsvFile, dtype={"uid": str})

        slack_channel_column = "slack_channel"
        assignments = self._paper_assignments(csv_data)

        csv_data = slackUtils.populate_channel_names(
            csv_data,
            slack_channel_column,
            lambda row, _: title2channelID(
                row["title"],
                session_number=assignments[row["uid"]].session_index,
                paper_number=assignments[row["uid"]].position,
            ),
        )

        print("Data output at: ", csv_data)
        # Updating the file with the details to be able to write the slack columns.
        csv_data.to_csv(self.papersCsvFile, index=False)
        print(
            f'Paper channel names generated. Please paste the updated "{slack_channel_column}" column back into the Google Sheet.'
        )

    def createSlackChannels(self, *_):
        if self.papersCsvFile is None:
            raise Exception("self.papersCsvFile passed in contructor is null")

        # Reading the papers data.
        csv_data = pd.read_csv(self.papersCsvFile, dtype={"uid": str})
        slack_channel_column = "slack_channel"
        channel_names = [
            str(name).strip() for name in csv_data[slack_channel_column].tolist() if str(name).strip()
        ]

        with tqdm(channel_names, desc="Creating Slack channels", unit="channel") as progress:
            slackUtils.createSlackChannels(progress, is_private=False, quiet=True)

        #  force reloading all channel data.
        slackUtils.loadAllChannelData()

        # Adding the channel link to the file.
        slackUtils.write_channel_links_to_csv(
            csv_data,
            self.papersCsvFile,
            slackUtils,
            slack_channel_column,
            remind_to_paste_to_sheet=True,
        )

    def setSlackChannelDescription(self):
        if self.papersCsvFile is None:
            raise Exception("self.papersCsvFile passed in contructor is null")
        if self.eventsCsvFile is None:
            raise Exception("eventsCsvFile passed in constructor is null")

        csv_data = pd.read_csv(self.papersCsvFile, dtype={"uid": str})
        events_data = pd.read_csv(self.eventsCsvFile)
        assignments = self._paper_assignments(csv_data)
        site_base_url = load_site_config(self.data_path)["miniconf_url"]

        poster_session_channels = {}
        oral_session_channels = {}
        for _, event in events_data.iterrows():
            category = event["category"]
            if category not in ("Poster session", "Oral session"):
                continue

            session = int(str(event["title"]).rsplit("-", 1)[1].strip())
            channel_name = (
                "" if pd.isna(event["slack_channel"])
                else str(event["slack_channel"]).strip()
            )
            if not channel_name:
                raise Exception(
                    f"{event['title']} is missing slack_channel. "
                    "Run setup-event-channels and create-event-channels first."
                )

            channel_id = slackUtils.getChannelID(channel_name)
            if channel_id is None:
                raise Exception(
                    f"{category} channel '{channel_name}' does not exist in Slack. "
                    "Run create-event-channels first."
                )

            if category == "Poster session":
                poster_session_channels[session] = channel_id
            else:
                oral_session_channels[session] = channel_id

        with tqdm(csv_data.iterrows()) as pbar:
            pbar.set_description("Setting Slack channel descriptions")
            for index, row in pbar:
                channel_name = row["slack_channel"]
                title = row["title"]
                paper_id = row["uid"]
                authors = (
                    row["authors_and_affil"]
                    .replace("*", "")
                    .replace(";", ",")
                    .replace("  ", " ")
                )
                authors = (
                    re.sub(r"\s*\(.*?\)", "", authors).replace("(", "").replace(")", "")
                )

                session = assignments[paper_id].session_index
                poster_channel_id = poster_session_channels[session]
                oral_channel_id = oral_session_channels[session]
                poster_channel_link = f"<#{poster_channel_id}>"
                oral_channel_link   = f"<#{oral_channel_id}>"
                topic = f"Paper {paper_id}: {title}"
                purpose = slackUtils.truncateText(
                    f"_\nPaper, poster, & more: <{site_base_url}/poster_{paper_id}.html>\n"
                    f"Find Zoom links in the channel descriptions of {oral_channel_link} and {poster_channel_link}.\n"
                    f'"{title}". {authors}'
                , 250)

                slackUtils.updateTopicandPurpose(channel_name, topic, purpose)
                pbar.set_postfix(channel=channel_name)
