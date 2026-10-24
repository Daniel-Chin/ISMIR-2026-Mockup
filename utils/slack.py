# Written by Prashant Mishra (GitHub: recreationdevelopers) for ISMIR 2022, and next set of events
# https://prashantmishra.xyz
# hi@prashantmishra.xyz
#
# Co-Author: Venkatakrishnan V K (GitHub: venkatKrishnan86)
# venkat86556@gmail.com

import os
import re
from pathlib import Path
import csv
from collections.abc import Callable
import time

import pandas as pd
import slack_sdk
from dotenv import load_dotenv
from slack_sdk.errors import SlackApiError
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler

from utils.shared import format_session_window, load_conference_timezone_name, load_site_config
from utils.zoom_redirect import build_zoom_redirect_url, load_zoom_redirect_access_token

# [Workaround 1 Step 1]
# This step is to be used if you get a [SSL: CERTIFICATE_VERIFY_FAILED] error
import ssl
import certifi

ssl_context = ssl.create_default_context(cafile=certifi.where())

env_path = Path(".") / ".env"
load_dotenv(dotenv_path=env_path)

def configure_clients(is_mockup: bool = False) -> None:
    """Select one workspace's credentials and discard workspace-specific caches.

    Missing tokens stay empty, allowing local-only actions without credentials.
    Mockup mode never falls back to live tokens.
    """
    global client_bot, client_user, _user_maps, _channel_maps, _workspace_url
    prefix = "MOCKUP_" if is_mockup else ""
    client_bot = slack_sdk.WebClient(
        token=os.environ.get(f"{prefix}SLACK_BOT_TOKEN", ""), ssl=ssl_context
    )
    client_user = slack_sdk.WebClient(
        token=os.environ.get(f"{prefix}SLACK_USER_TOKEN", ""), ssl=ssl_context
    )
    for client in (client_bot, client_user):
        client.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=5))
    _user_maps = None
    _channel_maps = None
    _workspace_url = None


configure_clients()


def getWorkspaceURL() -> str:
    """Workspace base URL (e.g. https://ismir2026-organizers.slack.com/), from auth.test."""
    global _workspace_url
    if _workspace_url is None:
        url = client_bot.auth_test().data["url"]  # type: ignore
        assert url
        _workspace_url = url if url.endswith("/") else url + "/"
    return _workspace_url


def getChannelURL(channel_id: str) -> str:
    return f"{getWorkspaceURL()}archives/{channel_id}"

# Slack recommends requesting at most 200 items per page on cursor-paginated
# methods (users.list, conversations.list, conversations.members).
PAGE_LIMIT = 200


def normalize_channel_title(title: str, max_words: int | None = 3) -> str:
    cleaned_title = str(title or "").strip().lower()
    cleaned_title = re.sub(r"[^a-z0-9_]+", "-", cleaned_title)
    cleaned_title = re.sub(r"[-_]+", "-", cleaned_title)
    cleaned_title = cleaned_title.strip("-")
    parts = [part for part in cleaned_title.split("-") if part]
    return "-".join(parts[:max_words])


def build_channel_name(prefix: str, title: str, max_words: int | None = 3) -> str:
    slug = normalize_channel_title(title, max_words=max_words)
    sanitized_prefix = re.sub(r"[^a-z0-9_]+", "-", str(prefix or "").strip().lower())
    sanitized_prefix = sanitized_prefix.strip("-")
    if sanitized_prefix and slug:
        return f"{sanitized_prefix}-{slug}"
    return slug or sanitized_prefix


def ensure_channel_url_column(csv_data: pd.DataFrame) -> pd.DataFrame:
    if "channel_url" not in csv_data.columns:
        csv_data["channel_url"] = ""
    csv_data["channel_url"] = csv_data["channel_url"].fillna("").astype(str)
    return csv_data


def populate_channel_names(
    csv_data: pd.DataFrame,
    channel_column_name: str,
    channel_name_factory: Callable[[pd.Series, int], str],
) -> pd.DataFrame:
    if channel_column_name not in csv_data.columns:
        csv_data[channel_column_name] = pd.Series(["" for _ in range(len(csv_data))], dtype="object")
    else:
        csv_data[channel_column_name] = csv_data[channel_column_name].astype("object")
    csv_data.loc[:, channel_column_name] = pd.Series(["" for _ in range(len(csv_data))], dtype="object")

    for index, row in csv_data.iterrows():
        csv_data.loc[index, channel_column_name] = channel_name_factory(row, index)

    return csv_data


def write_channel_links_to_csv(
    csv_data: pd.DataFrame,
    csv_path: str,
    slack_client,
    channel_column_name: str,
    remind_to_paste_to_sheet: bool = False,
    row_mask=None,
) -> None:
    csv_data = ensure_channel_url_column(csv_data)
    selected = csv_data if row_mask is None else csv_data.loc[row_mask]
    for index, channel_name in selected[channel_column_name].fillna("").items():
        channel_name = str(channel_name).strip().lstrip("#")
        if not channel_name:
            continue
        channel_id = slack_client.getChannelID(channel_name)
        if channel_id is None:
            raise LookupError(f"Channel {channel_name} does not exist in the workspace.")
        csv_data.loc[index, "channel_url"] = slack_client.getChannelURL(channel_id)
    csv_data.to_csv(csv_path, index=False)
    if remind_to_paste_to_sheet:
        print(
            "Channel setup complete. Please paste the updated slack_channel and channel_url columns back into the Google Sheet when you are done."
        )


# Sending Message to a particular channel as a Bot. The Bot MUST be added to the channel first.
# chat_postMessage requires the chat:write bot scope
def postMessageToASlackChannelAsBot(channelName, messageString):
    result = client_bot.chat_postMessage(channel=channelName, text=messageString)
    print(result)


# Creating Channel as Bot. Requires the app to be first installed to the domain
# conversations_create requires the channels:manage bot scope and groups:write FOR PRIVATE channels
def createSlackChannelAsBot(channelName, boolChannelPrivacyON, *, quiet=False):
    # Call the conversations.create method using the WebClient
    result = client_bot.conversations_create(
        # The name of the conversation
        name=channelName,
        is_private=boolChannelPrivacyON,
    )
    # Log the result which includes information like the ID of the conversation
    if result['ok']:
        if not quiet:
            print("Channel Created!")
    else:
        print('Failed to create channel.')
        print(result)
        input("Press Enter to continue...")
    # Keep the cached channel maps in sync without refetching the full list
    if _channel_maps is not None:
        _channel_maps[0][result["channel"]["name"]] = result["channel"]["id"]
        _channel_maps[1][result["channel"]["id"]] = result["channel"]["name"]


# Get all user data. Returns the data as a dictionary
# users_list requires bot scope 'users:read' and 'users:read.email' (Required for email)
def get_all_user_data():
    all_user_data = []

    # Iterating the SlackResponse follows response_metadata.next_cursor, so
    # every page is fetched (a single call returns at most one page).
    users_array = []
    for page in client_bot.users_list(limit=PAGE_LIMIT):
        users_array.extend(page["members"])

    for user in users_array:
        # Skip deactivated accounts and bots: they can't be invited to
        # channels, and their missing emails would collide in the lookup maps
        if user.get("deleted") or user.get("is_bot") or user["id"] == "USLACKBOT":
            continue
        # Key user info on their unique user ID
        user_id = user["id"]
        user_email = user["profile"].get(
            "email"
        )  # using .get() method to avoid error in the case of Bots, that don't have "email" value
        if user_email is not None and "is_email_confirmed" in user:
            is_email_confirmed = user["is_email_confirmed"]
        else:
            is_email_confirmed = False

        # print (user_id)
        # print (user_email)
        # print ("Email confirmation: " + str(is_email_confirmed))
        # Store the entire user object (you may not need all of the info)

        all_user_data.append(
            {
                "user_id": user_id,
                "user_email": user_email,
                "Email_Confirmed": is_email_confirmed,
            }
        )

    # print(all_user_data)
    return all_user_data


# User lookup maps, fetched from the Slack API on first use and cached.
_user_maps = None


def _get_user_maps():
    global _user_maps
    if _user_maps is None:
        all_user_data = get_all_user_data()
        _user_maps = (
            {
                user["user_email"]: user["user_id"]
                for user in all_user_data
                if user["user_email"] is not None
            },
            {user["user_id"]: user["user_email"] for user in all_user_data},
        )
    return _user_maps


# Get all channel data
# conversations_list requires the channels:read bot scope
def get_all_channels_data():
    all_channel_data = []

    # conversations_list defaults to public_channel, so we add private_channels as well here
    channelDataType = "public_channel,private_channel"

    # Paginate: Slack may return fewer than `limit` channels per page even
    # when more remain, so a single call can silently miss channels.
    channels_array = []
    for page in client_bot.conversations_list(types=channelDataType, limit=PAGE_LIMIT):
        channels_array.extend(page["channels"])

    # print(channels_array)

    for channel in channels_array:
        # Key conversation info on its unique ID
        channel_name = channel["name"]
        channel_id = channel["id"]

        # print (channel_id)

        all_channel_data.append(
            {"channel_name": channel_name, "channel_id": channel_id}
        )

    # print (all_channel_data)
    return all_channel_data


# Channel lookup maps, fetched from the Slack API on first use and cached.
_channel_maps = None


def _get_channel_maps():
    global _channel_maps
    if _channel_maps is None:
        channelsData = get_all_channels_data()
        _channel_maps = (
            {
                channel["channel_name"]: channel["channel_id"]
                for channel in channelsData
            },
            {
                channel["channel_id"]: channel["channel_name"]
                for channel in channelsData
            },
        )
    return _channel_maps


# Invalidate the cached channel maps so the next lookup refetches from the API
# (call after creating channels).
def loadAllChannelData():
    global _channel_maps
    _channel_maps = None


# Obtain Channel ID when given the channel name
def getChannelID(channelName):
    return _get_channel_maps()[0].get(channelName, None)


# Obtain User ID given user email
def getUserID(user_email):
    return _get_user_maps()[0].get(user_email, None)


# Obtain user email given user id
def getUserEmail(user_id):
    return _get_user_maps()[1].get(user_id, None)


# Adding member to channel.
# conversations_invite requires bot scope channels:manage (and optionally user scope channels:write)
def addUserIDsToASlackChannelById(channelId, userIDs):
    """
    channelID: Channel ID
    userIDs: List of user IDs to be invited
    """

    return client_bot.conversations_invite(channel=channelId, users=userIDs)


# Checks if the channel name already exists in the list of all public and private channels where the bot is added to
def isChannel(channelName):
    return channelName in _get_channel_maps()[0]


# Creating all the private slack channels as given in the papers-full.csv file
# This function ONLY creates the channel with the bot added to it as of now
# Slack has a limit on creating new channels at one run time (=90)
def createPrivateSlackChannels(csvFile, channelColumnName):
    paper_data = pd.read_csv(csvFile)
    channels = paper_data[channelColumnName]
    for channelName in channels:
        if not isChannel(channelName):
            createSlackChannelAsBot(channelName, True)


def createSlackChannels(channels, *, is_private=False, quiet=False):
    for channelName in channels:
        if not isChannel(channelName):
            createSlackChannelAsBot(channelName, is_private, quiet=quiet)


def createEmptyLinkColumnInCSVifNotPresent(csvFile, column_name, newCsvFile=None):
    """
    Parameters:
    -------------
    csvFile: The csv file to be read
    column_name: The name of the empty column
    newCsvFile (string): If None, the function will write a new column in csvFile, else will do so in a newCsvFile
    """
    paper_data = pd.read_csv(csvFile)
    for columns in paper_data:
        if columns == column_name:
            print("Column Already Exists")
            return
    paper_data[column_name] = ""
    if newCsvFile is None:
        paper_data.to_csv(csvFile, index=False)
    else:
        paper_data.to_csv(newCsvFile, index=False)


def addChannelLinksToCSV(csvFile, channelColumnName, newCsvFile=None):
    """
    Parameters:
    -------------
    csvFile: The csv file to be read
    channelColumnName: The name of the column containing channel names
    newCsvFile (string): If None, the function will overwrite in csvFile, else will write the csvFile with links in a newCsvFile
    """
    if newCsvFile is not None:
        createEmptyLinkColumnInCSVifNotPresent(csvFile, "channel_url", newCsvFile)
        paper_data = pd.read_csv(newCsvFile)
    else:
        createEmptyLinkColumnInCSVifNotPresent(csvFile, "channel_url")
        paper_data = pd.read_csv(csvFile)

    # An all-empty CSV column is inferred as float64 by pandas. Cast it before
    # assigning URL strings (pandas 2.x rejects the implicit dtype change).
    paper_data["channel_url"] = paper_data["channel_url"].fillna("").astype(str)

    channels = paper_data[channelColumnName]
    for i, channelName in enumerate(channels):
        if isChannel(channelName):
            paper_data.loc[
                i, "channel_url"
            ] = getChannelURL(getChannelID(channelName))
        else:
            print(
                f"Channel {channelName} does not exist in the workspace. Skipping link creation."
            )

    if newCsvFile is not None:
        paper_data.to_csv(newCsvFile, index=False)
    else:
        paper_data.to_csv(csvFile, index=False)


def _levenshtein_distance(left: str, right: str) -> int:
    left = str(left or "")
    right = str(right or "")

    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)

    prev_row = list(range(len(right) + 1))
    for i, left_char in enumerate(left, start=1):
        current_row = [i]
        for j, right_char in enumerate(right, start=1):
            insert_cost = current_row[j - 1] + 1
            delete_cost = prev_row[j] + 1
            substitute_cost = prev_row[j - 1] + (left_char != right_char)
            current_row.append(min(insert_cost, delete_cost, substitute_cost))
        prev_row = current_row
    return prev_row[-1]


def _is_channel_update_match(actual: str, expected: str, max_distance_portion: float = .1) -> bool:
    if actual == expected:
        return True

    candidate_actual = " ".join(str(actual or "").split())
    candidate_expected = " ".join(str(expected or "").split())
    if not candidate_actual or not candidate_expected:
        return False

    distance = _levenshtein_distance(candidate_actual.lower(), candidate_expected.lower())
    distance_portion = distance / max(len(candidate_actual), len(candidate_expected))
    # print(f'{distance_portion = }')
    return distance_portion <= max_distance_portion


def _delete_generated_channel_log(
    channel_id, update_type, expected_value, action_time: float,
):
    """
    Slack posts a bot-authored system message when a channel topic or purpose
    is changed. The API call itself does not always return a message timestamp,
    so we look through recent history for the bot's matching log entry and delete
    it to avoid stale announcements.
    """
    auth_info = client_bot.auth_test()

    bot_user_id = auth_info.data['user_id'] # type: ignore
    assert bot_user_id

    expected_text = " ".join(str(expected_value or "").split()).strip()
    assert expected_text

    for retry_i in range(3):
        history = client_bot.conversations_history(
            channel=channel_id, limit=20, oldest=str(int(action_time) - 10),
        )

        messages = history.get("messages", [])
        for message in messages:
            if message.get("user") != bot_user_id:
                continue

            text = " ".join(str(message.get("text", "") or "").split()).strip()
            if not text:
                continue

            target_prefix = "set the channel"
            if text.lower().startswith(target_prefix.lower()):
                _, message_value = text.split(': ', 1)
                if _is_channel_update_match(message_value, expected_text):
                    ts = message.get("ts")
                    if ts:
                        client_user.chat_delete(channel=channel_id, ts=ts)
                        return

        print('Not found. Maybe too soon? Retrying...')
        time.sleep([1, 10, 0][retry_i])
    raise RuntimeError("Failed to find matching channel log message.")


def updateTopicandPurpose(channelName, topic, purpose):
    """
    Updates the topic and purpose of a Slack channel.
    Requires channels:manage and groups:write bot scopes.
    Also makes the app/bot join the channel, which is required.
    """
    channel_id = getChannelID(channelName)
    assert channel_id is not None, "Channel ID should not be None"

    channel_info = client_bot.conversations_info(channel=channel_id)
    channel = channel_info.get("channel", {})
    is_member = channel.get("is_member", False)
    current_topic = channel.get("topic", {}).get("value", "")
    current_purpose: str = channel.get("purpose", {}).get("value", "")

    if not is_member:
        client_bot.conversations_join(channel=channel_id)

    if current_topic != topic:
        action_time = time.time()
        client_bot.conversations_setTopic(channel=channel_id, topic=topic)
        _delete_generated_channel_log(channel_id, "topic", topic, action_time)

    current_purpose = current_purpose.replace('&amp;', '&')
    # print('current_purpose')
    # print(current_purpose)
    # print('purpose')
    # print(purpose)
    # print(f'{current_purpose == purpose = }')
    # input('enter...')
    if current_purpose != purpose:
        action_time = time.time()
        client_bot.conversations_setPurpose(channel=channel_id, purpose=purpose)
        _delete_generated_channel_log(channel_id, "purpose", purpose, action_time)


# Checks if user is already in the workspace
# users.read bot scope required
def isUserAlreadyInWorkspace(user_email):
    return user_email in _get_user_maps()[0]


# Returns the list of members' emails already in the channel 'channelName'
# channels.read and groups:read bot scope required
# Returns None for bots
def memberEmailsAlreadyInChannel(channelName):
    channel_id = getChannelID(channelName)
    assert channel_id is not None, "Channel ID should not be None"
    members = [getUserEmail(user_id) for user_id in memberIDsInChannel(channel_id)]
    return members


def memberIDsInChannel(channel_id):
    # Paginate: conversations.members returns at most one page per call
    member_ids = []
    for page in client_bot.conversations_members(channel=channel_id, limit=PAGE_LIMIT):
        member_ids.extend(page["members"])
    return member_ids


# Checks if a user already exists in a channel
def isUserAlreadyInChannel(user_email, channelName):
    members = memberEmailsAlreadyInChannel(channelName)
    # for member in members:
    #     if member == user_email:
    #         return True
    # return False
    return user_email in members


# Upto 1000 users can be invited
# channels:manage and groups:write bot scopes required
def inviteUserToChannel(user_email, channelName):
    if not isUserAlreadyInChannel(user_email, channelName):
        userID = getUserID(user_email)
        channelID = getChannelID(channelName)
        if userID is None:
            raise LookupError(f"User {user_email} does not exist in the workspace.")

        addUserIDsToASlackChannelById(channelID, userID)
        print("Invitation Sent")
    else:
        print(
            "Either member already exists in the channel or no such member exists in the workspace"
        )


# Upto 1000 users can be invited
# channels:manage and groups:write bot scopes required
def inviteUsersToChannel(user_emails, channelName):
    emails_already_in_channel = memberEmailsAlreadyInChannel(channelName)
    userIDs = []
    for user_email in user_emails:
        if user_email in emails_already_in_channel:
            continue
        userID = getUserID(user_email)
        if userID is None:
            raise LookupError(f"User {user_email} does not exist in the workspace.")
        userIDs.append(userID)
    if not userIDs:
        print("No users to invite.")
        return
    channelID = getChannelID(channelName)

    addUserIDsToASlackChannelById(channelID, userIDs)
    print("Invitation Sent")


def add_all_workspace_members_to_channel(channel_name: str):
    """
    Invites every active, non-bot workspace member to the provided channel.
    Members who are already in the channel are skipped.
    """
    channel_id = getChannelID(channel_name)
    if channel_id is None:
        raise LookupError(f"Channel {channel_name} does not exist in the workspace.")

    # Paginate through current channel members so we only invite missing users.
    existing_member_ids = set()
    for page in client_bot.conversations_members(channel=channel_id, limit=PAGE_LIMIT):
        existing_member_ids.update(page["members"])

    all_workspace_user_ids = set(_get_user_maps()[1].keys())
    user_ids_to_invite = list(all_workspace_user_ids - existing_member_ids)

    if not user_ids_to_invite:
        print("No users to invite.")
        return

    # Slack conversations.invite accepts up to 1000 users per call.
    chunk_size = 1000
    for start in range(0, len(user_ids_to_invite), chunk_size):
        invite_chunk = user_ids_to_invite[start : start + chunk_size]
        try:
            addUserIDsToASlackChannelById(channel_id, invite_chunk)
        except SlackApiError as e:
            msg = e.response['error']
            print(f"Error inviting users: {msg}")
            if msg.strip() == 'not_in_channel':
                print('Hint: the inviting bot must be a member of the channel first.')
            raise

    print(
        f"Invitation Sent to {len(user_ids_to_invite)} user(s) for channel {channel_name}."
    )

def truncateText(text: str, max_length: int) -> str:
    """
    Truncates the text to the specified maximum length, adding an ellipsis if truncated.
    """
    if len(text) <= max_length:
        return text
    return text[:max_length - 3] + "..."

def batch_set_channel_description_interactive(sitedata_dir: str):
    '''
    A CLI session to batch set the description (purpose) of each channel.  
    '''

    EXCLUDE = []

    def render(
        category: str, zoom_link: str, friendly_time_description: str, 
    ):
        buf = []
        buf.append('_\nSchedule: ')
        buf.append(friendly_time_description)
        buf.append('\n')
        category_ = category.lower().strip()
        if category_ == 'poster session':
            buf.append("During that time, use this Zoom room for live interaction with authors and audiences:\n")
            buf.append('<' + zoom_link + '>')
        else:
            buf.append("If you aren't onsite, you can join the ")
            match category_:
                case 'keynote session' | 'panel session':
                    buf.append(f"Webinar: <{zoom_link}>\nWe'll take Q&A there as well as here on Slack!")
                case 'oral session':
                    buf.append(f"livestream: <{zoom_link}>\nNo time for live Q&A; Discuss on Slack!")
                case _:
                    buf.append(f"Webinar: <{zoom_link}>\nStart your discussion here on Slack!")
        return ''.join(buf)

    script_dir = Path(__file__).parent
    sitedata_path = script_dir.parent / sitedata_dir
    conference_timezone = load_conference_timezone_name(str(sitedata_path))
    events_csv_path = sitedata_path / "events.csv"
    with open(events_csv_path, 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            title = row['title']
            uid_ = row['uid']
            category = row['category']
            slack_channel = row['slack_channel']
            start_date = row['start_date']
            start_time = row['start_time']
            end_time = row['end_time']
            print('\nEvent:', title)
            if category.lower().strip() in EXCLUDE:
                # print(f'Do you want to skip it, because {category = }?')
                # while True:
                #     input_ = input('y/n? ').strip().lower()
                #     if input_ in [*'yn']:
                #         break
                # if input_ == 'y':
                continue
            webinar_link = build_zoom_redirect_url(
                load_site_config(sitedata_dir)['miniconf_url'], 
                uid_,
                load_zoom_redirect_access_token(),
            )
            channel_id = getChannelID(slack_channel)
            if channel_id is None:
                print(f'Channel {slack_channel} does not exist in the workspace. Skipping...')
                # input('Press Enter...')
                continue
            channel_info = client_bot.conversations_info(channel=channel_id)
            channel = channel_info.get('channel', {})
            current_description = channel.get('purpose', {}).get('value', '').replace('&amp;', '&')
            current_topic = channel.get('topic', {}).get('value', '')
            new_description = render(category, webinar_link, format_session_window(
                start_date, start_time, end_time,
                conference_timezone,
            ))
            if new_description == current_description:
                print('No change detected, skipping.')
                # input('Press Enter to continue...')
                continue
            print('Existing description: """')
            print(current_description)
            print('"""')
            print('\nNew description being proposed: """')
            print(new_description)
            print('"""')
            # print('Apply this update, or skip?')
            # while True:
            #     input_ = input('a/s? ').strip().lower()
            #     if input_ in [*'as']:
            #         break
            # if input_ == 'a':
            updateTopicandPurpose(slack_channel, current_topic or title, new_description)
            # else:
            #     print('Skipped.')
