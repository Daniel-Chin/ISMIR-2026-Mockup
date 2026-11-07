import re

import pandas as pd

from utils import slack as slackUtils


def event_channel_name(row, index):
    title = str(row.get("title", "") or "").strip()
    if row.get("category") == "Tutorials":
        title = re.sub(r"^(T\d+)\s*\([MA]\)\s*:", r"\1", title, flags=re.IGNORECASE)
        return slackUtils.build_channel_name("tutorial", title, max_words=5)
    BLACKLIST = [
        "lunch", 'registration', 
        'welcome reception', 'late-breaking/demo',
    ]
    if title.lower() in BLACKLIST:
        return ""
    award_session = re.fullmatch(
        r"★?\s*Award\s+Nominees\s+Oral\s+Session\s*-\s*(\d+)",
        title,
        flags=re.IGNORECASE,
    )
    if award_session:
        return f"award-nominees-{award_session.group(1)}"
    if str(row.get("category", "")).strip().lower() == "special":
        title = re.sub(r"^lunch\s+", "", title, flags=re.IGNORECASE)
        return slackUtils.build_channel_name("", title, max_words=None)
    return slackUtils.build_channel_name("", title)


class Events:
    def __init__(self, eventsCsvFile, useDummyValues, *, tutorials_only=False):
        self.eventsCsvFile = eventsCsvFile
        self.useDummyValues = useDummyValues
        self.tutorials_only = tutorials_only

    def _channel_rows(self, csv_data):
        tutorial_mask = csv_data["category"].eq("Tutorials")
        return tutorial_mask if self.tutorials_only else ~tutorial_mask

    def setupSlackChannels(self, *_):
        if self.eventsCsvFile is None:
            raise Exception("self.eventsCsvFile passed in constructor is null")

        csv_data = pd.read_csv(self.eventsCsvFile, keep_default_na=False, na_values=[""])
        slack_channel_column = "slack_channel"
        row_mask = self._channel_rows(csv_data)
        if slack_channel_column not in csv_data:
            csv_data[slack_channel_column] = ""
        csv_data[slack_channel_column] = csv_data[slack_channel_column].astype(object)
        selected = slackUtils.populate_channel_names(
            csv_data.loc[row_mask].copy().reset_index(drop=True),
            slack_channel_column,
            event_channel_name,
        )

        csv_data.loc[row_mask, slack_channel_column] = selected[slack_channel_column].to_numpy()
        csv_data.to_csv(self.eventsCsvFile, index=False)
        print("Data output at: ", csv_data)
        print(
            f'Channel names generated. Please paste the updated "{slack_channel_column}" column back into the Google Sheet.'
        )

    def createSlackChannels(self, slack_client=None, *_):
        if self.eventsCsvFile is None:
            raise Exception("self.eventsCsvFile passed in constructor is null")

        csv_data = pd.read_csv(self.eventsCsvFile, keep_default_na=False, na_values=[""])
        slack_channel_column = "slack_channel"
        row_mask = self._channel_rows(csv_data)
        channel_names = [str(name).strip().lstrip("#") for name in csv_data.loc[
            row_mask, slack_channel_column
        ].fillna("").tolist() if str(name).strip().lstrip("#")]

        channel_kind = "tutorial" if self.tutorials_only else "event"
        visibility = "private" if self.tutorials_only else "public"
        print(f"Creating {visibility} {channel_kind} Slack channels")
        target_client = slack_client or slackUtils
        target_client.createSlackChannels(channel_names, is_private=self.tutorials_only)
        target_client.loadAllChannelData()

        slackUtils.write_channel_links_to_csv(
            csv_data,
            self.eventsCsvFile,
            target_client,
            slack_channel_column,
            remind_to_paste_to_sheet=True,
            row_mask=row_mask,
        )
