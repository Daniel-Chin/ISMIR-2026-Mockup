import re

import pandas as pd
from tqdm import tqdm

from utils import slack as slackUtils


def lbd_channel_name(row, _):
    return slackUtils.build_channel_name(f"lbd{row['uid']}", row["title"])


class Lbds:
    def __init__(self, lbdsCsvFile):
        self.lbdsCsvFile = lbdsCsvFile

    def setupSlackChannels(self):
        csv_data = pd.read_csv(self.lbdsCsvFile, dtype=str, keep_default_na=False)
        csv_data = slackUtils.populate_channel_names(csv_data, "slack_channel", lbd_channel_name)
        csv_data.to_csv(self.lbdsCsvFile, index=False)
        print(
            'LBD channel names generated. Please paste the updated "slack_channel" column back into the Google Sheet.'
        )

    def createSlackChannels(self):
        csv_data = pd.read_csv(self.lbdsCsvFile, dtype=str, keep_default_na=False)
        channel_names = [
            str(name).strip() for name in csv_data["slack_channel"].fillna("").tolist() if str(name).strip()
        ]

        with tqdm(channel_names, desc="Creating Slack channels", unit="channel") as progress:
            slackUtils.createSlackChannels(progress, is_private=False, quiet=True)

        slackUtils.loadAllChannelData()

        slackUtils.write_channel_links_to_csv(
            csv_data,
            self.lbdsCsvFile,
            slackUtils,
            "slack_channel",
            remind_to_paste_to_sheet=True,
        )


# ---------- LBD group channels (lbds_grouping.csv: group_id, theme, channel_url) ----------
# One public channel per group, e.g. lbd-g1-music-generation-computational, described by its theme.

def lbd_group_channel_name(row, _):
    return slackUtils.build_channel_name(f"lbd-g{row['group_id']}", row["theme"])


def lbd_group_purpose(theme):
    """'A, B, and C' -> 'LBD topics: A, B, C' (the theme as the Warm-up Discussion shows it)."""
    return "LBD topics: " + re.sub(r",?\s+and\s+", ", ", str(theme or "").strip())


class LbdGroups:
    def __init__(self, groupingCsvFile):
        self.groupingCsvFile = groupingCsvFile

    def _read(self):
        return pd.read_csv(self.groupingCsvFile, dtype=str, keep_default_na=False)

    def setupSlackChannels(self):
        csv_data = slackUtils.populate_channel_names(self._read(), "slack_channel", lbd_group_channel_name)
        csv_data.to_csv(self.groupingCsvFile, index=False)
        for _, row in csv_data.iterrows():
            print(f"  {row['slack_channel']:<45} {lbd_group_purpose(row['theme'])}")
        print('LBD group channel names generated. Please paste the "slack_channel" column back into the Google Sheet.')

    def createSlackChannels(self):
        """Creates the missing channels, writes channel_url back, and sets each one's description."""
        csv_data = self._read()
        if "slack_channel" not in csv_data.columns:
            raise LookupError("No slack_channel column: run setup-lbd-group-channels first.")
        rows = [(str(r["slack_channel"]).strip().lstrip("#"), r["theme"]) for _, r in csv_data.iterrows()]
        rows = [(name, theme) for name, theme in rows if name]
        with tqdm([name for name, _ in rows], desc="Creating Slack channels", unit="channel") as progress:
            slackUtils.createSlackChannels(progress, is_private=False, quiet=True)
        slackUtils.loadAllChannelData()
        for name, theme in rows:
            slackUtils.updateTopicandPurpose(name, "", lbd_group_purpose(theme))
            print(f"  {name}: {lbd_group_purpose(theme)}")
        slackUtils.write_channel_links_to_csv(
            csv_data,
            self.groupingCsvFile,
            slackUtils,
            "slack_channel",
            remind_to_paste_to_sheet=True,
        )
