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
