import json
import os
import re
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
from dotenv import load_dotenv

from utils.shared import load_conference_timezone_name, load_site_config

accountCreds = None
accessToken = None
tokenExpireTime = None

_POSTER_SESSION_RE = re.compile(r"^Poster Session - \d+$")


def _load_conference_timezone(csvFilename=None):
    if csvFilename:
        return load_conference_timezone_name(
            str(Path(csvFilename).resolve().parent),
        )
    tz_name = os.environ.get("CONFERENCE_TIMEZONE", None)
    assert tz_name is not None
    return tz_name


def getAccountCreds():
    global accountCreds
    if accountCreds is None:
        load_dotenv(dotenv_path=Path(".") / ".env")
        try:
            accountCreds = {
                "accountId": os.environ["ZOOM_API_ACCOUNT_ID"],
                "clientId": os.environ["ZOOM_API_CLIENT_ID"],
                "clientSecret": os.environ["ZOOM_API_CLIENT_SECRET"],
            }
        except KeyError as missing:
            raise RuntimeError(
                f"Missing Zoom credential {missing} — add ZOOM_API_ACCOUNT_ID, "
                "ZOOM_API_CLIENT_ID and ZOOM_API_CLIENT_SECRET from a "
                "Server-to-Server OAuth app to .env"
            ) from None
    return accountCreds


def getAccessToken(accountCreds):
    """
    returns access token used in Zoom API calls
    """
    getTokenUrl = (
        "https://zoom.us/oauth/token"
        + f"?grant_type=account_credentials&account_id={accountCreds['accountId']}"
    )
    resp = requests.post(
        getTokenUrl, auth=(accountCreds["clientId"], accountCreds["clientSecret"])
    )
    respJson = resp.json()
    if "access_token" not in respJson:
        raise RuntimeError(f"Zoom OAuth token request failed: {respJson}")
    # token expire time in seconds since epoch
    tokenExpireTime = int(respJson["expires_in"]) - 10 + int(time.time())
    return (respJson["access_token"], tokenExpireTime)


def checkToken():
    global accessToken, tokenExpireTime
    if accessToken is None or tokenExpireTime is None or time.time() >= tokenExpireTime:
        accessToken, tokenExpireTime = getAccessToken(getAccountCreds())
    return (accessToken, tokenExpireTime)


def _breakoutRoomPayload(roomNames):
    return [
        {"name": name[:32], "participants": []}
        for name in roomNames[:50]
    ]


def _listPaginated(apiEndpointUrl, itemsKey):
    """All pages of a scheduled-item list endpoint, raising on any error page."""
    accessToken, _ = checkToken()
    headers = {
        "Authorization": f"Bearer {accessToken}",
        "content-type": "application/json",
    }
    items = []
    queryData = {"type": "scheduled", "page_size": 300}
    while True:
        resp = requests.get(apiEndpointUrl, params=queryData, headers=headers)
        respJson = resp.json()
        if itemsKey not in respJson:
            raise RuntimeError(f"Zoom {itemsKey} list request failed: {respJson}")
        items.extend(respJson[itemsKey])
        nextPageToken = respJson.get("next_page_token", "")
        if not nextPageToken:
            return items
        queryData = {
            "type": "scheduled",
            "page_size": 300,
            "next_page_token": nextPageToken,
        }


def getListOfMeetings():
    meetings = _listPaginated("https://api.zoom.us/v2/users/me/meetings", "meetings")
    return [
        (meeting["id"], meeting["topic"], meeting.get("join_url"))
        for meeting in meetings
    ]


def doesMeetingExist(key_type, key_val):
    """
    key_type: "topic" or "id"
    key_val: meeting topic (str) or meeting id (int)
    """
    meetingList = getListOfMeetings()
    # meetingList is a list of (id, topic, join_url) tuples
    if key_type == "topic":
        return key_val in [meeting[1] for meeting in meetingList]
    elif key_type == "id":
        return key_val in [meeting[0] for meeting in meetingList]
    else:
        raise ValueError(f"Invalid key_type ({key_type}) given to doesMeetingExist()")


def updateMeetingPasscode(meetingId, passcode):
    """Set the same passcode on an existing Zoom meeting."""
    if passcode is None:
        return None
    passcode = str(passcode).strip()
    if not passcode:
        return None

    accessToken, _ = checkToken()
    apiEndpointUrl = f"https://api.zoom.us/v2/meetings/{meetingId}"
    headers = {
        "Authorization": f"Bearer {accessToken}",
        "content-type": "application/json",
    }
    resp = requests.patch(
        apiEndpointUrl,
        data=json.dumps({"password": passcode}),
        headers=headers,
    )
    if resp.status_code != 204:
        raise RuntimeError(
            f"Zoom updateMeetingPasscode({meetingId}) failed: HTTP {resp.status_code} {resp.text}"
        )
    return resp.status_code


def createMeeting(
    meetingTopic,
    startTime,
    duration,
    breakoutRooms=None,
    timezone=None,
    passcode=None,
):
    """
    breakoutRooms: optional list of room names, pre-created in the meeting
    (host still opens them live). Zoom caps pre-assigned rooms at 50 and
    room names at 32 characters.
    """
    accessToken, _ = checkToken()
    apiEndpointUrl = "https://api.zoom.us/v2/users/me/meetings"
    headers = {
        "Authorization": f"Bearer {accessToken}",
        "content-type": "application/json",
    }
    meetingDetails = {
        "topic": meetingTopic,
        "type": 2,  # scheduled meeting
        "start_time": startTime,  # "2022-10-23T01:15:00", local to `timezone`
        "timezone": timezone,
        "settings": {
            "waiting_room": False,
            "join_before_host": True,
            "jbh_time": 0,  # anytime before host
        },
    }
    if passcode is not None:
        passcode = str(passcode).strip()
        if passcode:
            meetingDetails["password"] = passcode
    if breakoutRooms:
        meetingDetails["settings"]["breakout_room"] = {
            "enable": True,
            "rooms": _breakoutRoomPayload(breakoutRooms),
        }
    if duration:
        meetingDetails["duration"] = duration  # in minutes
    resp = requests.post(
        apiEndpointUrl, data=json.dumps(meetingDetails), headers=headers
    )
    try:
        respJson = resp.json()
    except requests.exceptions.JSONDecodeError as e:
        raise RuntimeError(
            f"Zoom createMeeting({meetingTopic!r}) failed: "
            f"HTTP {resp.status_code} {resp.text}"
        ) from e
    if "join_url" not in respJson:
        raise RuntimeError(f"Zoom createMeeting({meetingTopic!r}) failed: {respJson}")
    if breakoutRooms:
        _verifyBreakoutRooms(respJson["id"], breakoutRooms)
    return respJson


def getMeeting(meetingId):
    accessToken, _ = checkToken()
    apiEndpointUrl = f"https://api.zoom.us/v2/meetings/{meetingId}"
    headers = {
        "Authorization": f"Bearer {accessToken}",
        "content-type": "application/json",
    }
    respJson = requests.get(apiEndpointUrl, headers=headers).json()
    if "id" not in respJson:
        raise RuntimeError(f"Zoom getMeeting({meetingId}) failed: {respJson}")
    return respJson


def _verifyBreakoutRooms(meetingId, roomNames):
    """
    Zoom accepts settings.breakout_room on create/update but silently drops it
    when the account's breakout-room setting is off (and some accounts never
    persist API-defined rooms at all) — so read the meeting back and fail loud.
    """
    breakout = getMeeting(meetingId).get("settings", {}).get("breakout_room", {})
    persisted = [room.get("name") for room in breakout.get("rooms") or []]
    expected = [name[:32] for name in roomNames[:50]]
    if not breakout.get("enable") or sorted(persisted) != sorted(expected):
        raise RuntimeError(
            f"Breakout rooms did not persist on meeting {meetingId}: expected "
            f"{len(expected)} rooms, Zoom kept {persisted or 'none'}. Check that "
            "'Breakout room' is enabled under Settings -> Meeting -> In Meeting "
            "(Advanced) in the Zoom web portal."
        )


def deleteMeeting(meetingId):
    accessToken, _ = checkToken()
    apiEndpointUrl = f"https://api.zoom.us/v2/meetings/{meetingId}"
    headers = {
        "Authorization": f"Bearer {accessToken}",
        "content-type": "application/json",
    }
    resp = requests.delete(apiEndpointUrl, headers=headers)
    resp.raise_for_status()
    return resp.status_code


def updateMeetingBreakoutRooms(meetingId, roomNames):
    """Add/replace pre-created breakout rooms on an existing meeting."""
    accessToken, _ = checkToken()
    apiEndpointUrl = f"https://api.zoom.us/v2/meetings/{meetingId}"
    headers = {
        "Authorization": f"Bearer {accessToken}",
        "content-type": "application/json",
    }
    patch = {
        "settings": {
            "breakout_room": {
                "enable": True,
                "rooms": _breakoutRoomPayload(roomNames),
            }
        }
    }
    resp = requests.patch(apiEndpointUrl, data=json.dumps(patch), headers=headers)
    if resp.status_code != 204:
        raise RuntimeError(
            f"Zoom updateMeetingBreakoutRooms({meetingId}) failed: "
            f"HTTP {resp.status_code} {resp.text}"
        )
    _verifyBreakoutRooms(meetingId, roomNames)
    return resp.status_code  # 204 on success


def _durationMinutes(row):
    """Meeting length in minutes from HH:MM start_time/end_time columns; invalid or missing times raise."""
    start = datetime.strptime(str(row["start_time"]), "%H:%M")
    end = datetime.strptime(str(row["end_time"]), "%H:%M")
    minutes = int((end - start).total_seconds() / 60)
    if minutes <= 0:
        raise ValueError("Meeting end time must be after its start time")
    return minutes


def _clock_hhmm_to_minutes(clock):
    hh, mm = str(clock).strip().split(":")
    return int(hh) * 60 + int(mm)


def _sharedWebinarTopic(csvFilename=None):
    envTopic = os.environ.get("ZOOM_SHARED_WEBINAR_TOPIC")
    if envTopic and str(envTopic).strip():
        return str(envTopic).strip()

    if csvFilename:
        site_data_path = str(Path(csvFilename).resolve().parent)
        config = load_site_config(site_data_path)
        configName = str(config.get("name", "")).strip()
        if configName:
            return configName + " Livestream"

    raise RuntimeError(
        "Shared webinar topic not configured: set 'name' in sitedata/config.yml "
        "or ZOOM_SHARED_WEBINAR_TOPIC in the environment."
    )


def _sharedWebinarStartHHMM(csvFilename=None):
    envStart = os.environ.get("ZOOM_SHARED_WEBINAR_START_HHMM")
    if envStart and str(envStart).strip():
        return str(envStart).strip()

    if csvFilename:
        site_data_path = str(Path(csvFilename).resolve().parent)
        config = load_site_config(site_data_path)
        configStart = str(config.get("zoom_shared_webinar_start_hhmm", "")).strip()
        if configStart:
            return configStart

    raise RuntimeError(
        "Shared webinar start time not configured: set "
        "'zoom_shared_webinar_start_hhmm' in sitedata/config.yml or "
        "ZOOM_SHARED_WEBINAR_START_HHMM in the environment."
    )

def _sharedWebinarEndHHMM(csvFilename=None):
    envEnd = os.environ.get("ZOOM_SHARED_WEBINAR_END_HHMM")
    if envEnd and str(envEnd).strip():
        return str(envEnd).strip()

    if csvFilename:
        site_data_path = str(Path(csvFilename).resolve().parent)
        config = load_site_config(site_data_path)
        configEnd = str(config.get("zoom_shared_webinar_end_hhmm", "")).strip()
        if configEnd:
            return configEnd

    raise RuntimeError(
        "Shared webinar end time not configured: set "
        "'zoom_shared_webinar_end_hhmm' in sitedata/config.yml or "
        "ZOOM_SHARED_WEBINAR_END_HHMM in the environment."
    )


def _isPosterSessionRow(row, breakoutRooms=None):
    if breakoutRooms:
        return True
    category = str(row.get("category", "")).strip().lower()
    if category == "poster session":
        return True
    title = str(row.get("title", "")).strip()
    return _POSTER_SESSION_RE.match(title) is not None


def _sharedWebinarSchedule(nonPosterRows, csvFilename=None):
    """Build recurring webinar schedule from non-poster rows.

    Start date = earliest non-poster live event date.
    End date = latest non-poster live event date.
    Time window comes from explicit config/env values.
    """
    dates = pd.to_datetime(nonPosterRows["start_date"], errors="raise")
    firstDay = dates.min().strftime("%Y-%m-%d")
    lastDay = dates.max().strftime("%Y-%m-%d")
    startHHMM = _sharedWebinarStartHHMM(csvFilename)
    endHHMM = _sharedWebinarEndHHMM(csvFilename)
    startTime = f"{firstDay}T{startHHMM}:00"
    startMinutes = _clock_hhmm_to_minutes(startHHMM)
    endMinutes = _clock_hhmm_to_minutes(endHHMM)
    duration = endMinutes - startMinutes
    if duration <= 0:
        raise RuntimeError(
            "Invalid shared webinar window: "
            f"{startHHMM}-{endHHMM}"
        )
    recurrenceDays = (pd.to_datetime(lastDay) - pd.to_datetime(firstDay)).days + 1
    recurrence = {
        "type": 1,  # daily recurrence
        "repeat_interval": 1,
        "end_times": int(recurrenceDays),
    }
    return startTime, duration, recurrence


def getWebinar(webinarId):
    accessToken, _ = checkToken()
    apiEndpointUrl = f"https://api.zoom.us/v2/webinars/{webinarId}"
    headers = {
        "Authorization": f"Bearer {accessToken}",
        "content-type": "application/json",
    }
    respJson = requests.get(apiEndpointUrl, headers=headers).json()
    if "id" not in respJson:
        raise RuntimeError(f"Zoom getWebinar({webinarId}) failed: {respJson}")
    return respJson


def _webinarPayload(
    topic,
    startTime,
    duration,
    timezone=None,
    passcode=None,
    recurrence=None,
    includeType=True,
    includeQA=True,
):
    webinarType = 9 if recurrence else 5  # recurring fixed-time / single scheduled
    payload = {
        "topic": topic,
        "start_time": startTime,
        "duration": duration,
        "timezone": timezone,
        "settings": {
            "practice_session": True,
            "hd_video": True,
            "auto_recording": "cloud",
            "meeting_authentication": False,
            # No registration required.
            "approval_type": 2,
        },
    }
    if includeType:
        payload["type"] = webinarType
    if includeQA:
        payload["settings"]["question_and_answer"] = {"enable": True}
    if recurrence:
        payload["recurrence"] = recurrence
    if passcode is not None:
        passcode = str(passcode).strip()
        if passcode:
            payload["password"] = passcode
    return payload


def createZoomLinksIfNeeded(
    csvFilename,
    topicColumnId,
    zoomColumnId,
    indexColumnId,
    rowFilter=None,
    breakoutRoomsForRow=None,
    passcode=None,
    topicPrefix="",
):
    """
    Conference mode orchestrator:
    - poster sessions -> one meeting per row (with optional breakout rooms)
    - non-poster live events -> one shared webinar URL written to all rows

    Idempotent for both branches:
    - poster meetings are matched by topic
    - shared webinar is matched by SHARED_WEBINAR_TOPIC

    rowFilter: optional callable(row) -> bool; rows returning False are left alone.
    breakoutRoomsForRow: optional callable(row) -> list of room names (or None);
    rooms are pre-created in new meetings and patched onto backfilled ones.

    DEPRECATION NOTE:
    The old behavior (one meeting per filtered row) is preserved in
    createZoomMeetingLinksPerRow_DEPRECATED for compatibility.
    """
    csvData = pd.read_csv(csvFilename, index_col=indexColumnId)
    conferenceTimezone = _load_conference_timezone(csvFilename)
    # an all-empty link column reads back as float64; make it hold strings
    csvData[zoomColumnId] = csvData[zoomColumnId].astype("object")
    existingByTopic = {
        meeting[1]: meeting for meeting in getListOfMeetings()
    }  # (id, topic, join_url)
    posterCreated, posterBackfilled = 0, 0
    webinarCreated, webinarUpdated = 0, 0
    webinarRowsAssigned = 0

    posterRows = []
    nonPosterRows = []
    for index, row in csvData.iterrows():
        if rowFilter is not None and not rowFilter(row):
            continue
        rooms = breakoutRoomsForRow(row) if breakoutRoomsForRow else None
        if _isPosterSessionRow(row, rooms):
            posterRows.append((index, row, rooms))
        else:
            nonPosterRows.append((index, row))

    # save-on-exit: a raise partway through must not lose join_urls of meetings
    # already created (re-running would backfill them by topic, but the CSV
    # should never go stale on disk)
    try:
        for index, row, breakoutRooms in posterRows:
            topic = topicPrefix + row[topicColumnId]
            if topic in existingByTopic:
                posterBackfilled += 1
                if breakoutRooms:
                    updateMeetingBreakoutRooms(existingByTopic[topic][0], breakoutRooms)
                    print(f"patched {len(breakoutRooms)} breakout rooms onto: {topic}")
                meetingId = existingByTopic[topic][0]
                if passcode is not None:
                    updateMeetingPasscode(meetingId, passcode)
                    print(f"updated Zoom passcode on existing: {topic}")
                latestMeeting = getMeeting(meetingId)
                latestJoinUrl = latestMeeting.get("join_url")
                if not latestJoinUrl:
                    raise RuntimeError(
                        f"Zoom getMeeting({meetingId}) missing join_url while backfilling: {latestMeeting}"
                    )
                csvData.loc[index, zoomColumnId] = latestJoinUrl
                existingByTopic[topic] = (
                    meetingId,
                    latestMeeting.get("topic", topic),
                    latestJoinUrl,
                )
            else:
                startTime = f"{row['start_date']}T{row['start_time']}:00"
                respJson = createMeeting(
                    topic,
                    startTime,
                    _durationMinutes(row),
                    breakoutRooms,
                    timezone=conferenceTimezone,
                    passcode=passcode,
                )
                existingByTopic[topic] = (
                    respJson["id"],
                    respJson["topic"],
                    respJson["join_url"],
                )
                csvData.loc[index, zoomColumnId] = respJson["join_url"]
                posterCreated += 1
                rooms = (
                    f" ({len(breakoutRooms)} breakout rooms)" if breakoutRooms else ""
                )
                print(
                    f"created Zoom meeting: {topic} @ {startTime} "
                    f"{conferenceTimezone}{rooms}"
                )

        if nonPosterRows:
            nonPosterFrame = pd.DataFrame([row for _, row in nonPosterRows])
            webinarStart, webinarDuration, webinarRecurrence = _sharedWebinarSchedule(
                nonPosterFrame,
                csvFilename=csvFilename,
            )

            existingWebinar = None
            webinarTopic = topicPrefix + _sharedWebinarTopic(csvFilename)
            for webinarId, existingTopic, webinarJoinUrl in getListOfWebinars():
                if existingTopic == webinarTopic:
                    existingWebinar = (webinarId, webinarJoinUrl)
                    break

            if existingWebinar:
                webinarId = existingWebinar[0]
                updateWebinar(
                    webinarId,
                    webinarTopic,
                    webinarStart,
                    webinarDuration,
                    timezone=conferenceTimezone,
                    passcode=passcode,
                    recurrence=webinarRecurrence,
                )
                webinar = getWebinar(webinarId)
                webinarUpdated += 1
                print(
                    "updated shared Zoom webinar: "
                    f"{webinarTopic} @ {webinarStart} "
                    f"{conferenceTimezone} ({webinarDuration} min/day)"
                )
            else:
                webinar = createWebinar(
                    webinarTopic,
                    webinarStart,
                    webinarDuration,
                    timezone=conferenceTimezone,
                    passcode=passcode,
                    recurrence=webinarRecurrence,
                )
                webinarCreated += 1
                print(
                    "created shared Zoom webinar: "
                    f"{webinarTopic} @ {webinarStart} "
                    f"{conferenceTimezone} ({webinarDuration} min/day)"
                )

            webinarJoinUrl = webinar.get("join_url")
            if not webinarJoinUrl:
                raise RuntimeError(
                    f"Shared webinar missing join_url: {webinar}"
                )
            for index, _ in nonPosterRows:
                csvData.loc[index, zoomColumnId] = webinarJoinUrl
                webinarRowsAssigned += 1
    finally:
        csvData.to_csv(csvFilename)
        print(
            "createZoomLinksIfNeeded: "
            f"poster meetings {posterCreated} created, {posterBackfilled} backfilled; "
            f"shared webinar {webinarCreated} created, {webinarUpdated} updated; "
            f"{webinarRowsAssigned} non-poster rows assigned webinar URL "
            f"-> {csvFilename}"
        )
        print(f'You may want to copy the "{zoomColumnId}" column of "{csvFilename}" into Google Sheet.')


def createZoomMeetingLinksPerRow_DEPRECATED(
    csvFilename,
    topicColumnId,
    zoomColumnId,
    indexColumnId,
    rowFilter=None,
    breakoutRoomsForRow=None,
    passcode=None,
):
    """DEPRECATED: old behavior that creates one meeting per filtered CSV row."""
    print(
        "[DEPRECATED] createZoomMeetingLinksPerRow_DEPRECATED uses the old "
        "one-meeting-per-row behavior. Prefer createZoomLinksIfNeeded()."
    )
    csvData = pd.read_csv(csvFilename, index_col=indexColumnId)
    conferenceTimezone = _load_conference_timezone(csvFilename)
    csvData[zoomColumnId] = csvData[zoomColumnId].astype("object")
    existingByTopic = {meeting[1]: meeting for meeting in getListOfMeetings()}
    created, backfilled = 0, 0

    try:
        for index, row in csvData.iterrows():
            if rowFilter is not None and not rowFilter(row):
                continue
            topic = row[topicColumnId]
            breakoutRooms = breakoutRoomsForRow(row) if breakoutRoomsForRow else None
            if topic in existingByTopic:
                backfilled += 1
                if breakoutRooms:
                    updateMeetingBreakoutRooms(existingByTopic[topic][0], breakoutRooms)
                meetingId = existingByTopic[topic][0]
                if passcode is not None:
                    updateMeetingPasscode(meetingId, passcode)
                latestMeeting = getMeeting(meetingId)
                latestJoinUrl = latestMeeting.get("join_url")
                if not latestJoinUrl:
                    raise RuntimeError(
                        f"Zoom getMeeting({meetingId}) missing join_url while backfilling: {latestMeeting}"
                    )
                csvData.loc[index, zoomColumnId] = latestJoinUrl
                existingByTopic[topic] = (
                    meetingId,
                    latestMeeting.get("topic", topic),
                    latestJoinUrl,
                )
            else:
                startTime = f"{row['start_date']}T{row['start_time']}:00"
                respJson = createMeeting(
                    topic,
                    startTime,
                    _durationMinutes(row),
                    breakoutRooms,
                    timezone=conferenceTimezone,
                    passcode=passcode,
                )
                existingByTopic[topic] = (
                    respJson["id"],
                    respJson["topic"],
                    respJson["join_url"],
                )
                csvData.loc[index, zoomColumnId] = respJson["join_url"]
                created += 1
    finally:
        csvData.to_csv(csvFilename)
        print(
            f"createZoomMeetingLinksPerRow_DEPRECATED: {created} created, "
            f"{backfilled} backfilled -> {csvFilename}"
        )


def createWebinar(
    topic,
    startTime,
    duration,
    timezone=None,
    passcode=None,
    recurrence=None,
):
    accessToken, _ = checkToken()
    apiEndpointUrl = "https://api.zoom.us/v2/users/me/webinars"
    headers = {
        "Authorization": f"Bearer {accessToken}",
        "content-type": "application/json",
    }
    webinarDetails = _webinarPayload(
        topic,
        startTime,
        duration,
        timezone=timezone,
        passcode=passcode,
        recurrence=recurrence,
        includeType=True,
        includeQA=True,
    )
    resp = requests.post(
        apiEndpointUrl, data=json.dumps(webinarDetails), headers=headers
    )
    respJson = resp.json()
    if "join_url" not in respJson and "question_and_answer" in resp.text:
        webinarDetails = _webinarPayload(
            topic,
            startTime,
            duration,
            timezone=timezone,
            passcode=passcode,
            recurrence=recurrence,
            includeType=True,
            includeQA=False,
        )
        resp = requests.post(
            apiEndpointUrl, data=json.dumps(webinarDetails), headers=headers
        )
        respJson = resp.json()
    if "join_url" not in respJson:
        raise RuntimeError(f"Zoom createWebinar({topic!r}) failed: {respJson}")
    return respJson


def updateWebinar(
    webinarId,
    topic,
    startTime,
    duration,
    timezone=None,
    passcode=None,
    recurrence=None,
):
    accessToken, _ = checkToken()
    apiEndpointUrl = f"https://api.zoom.us/v2/webinars/{webinarId}"
    headers = {
        "Authorization": f"Bearer {accessToken}",
        "content-type": "application/json",
    }
    webinarDetails = _webinarPayload(
        topic,
        startTime,
        duration,
        timezone=timezone,
        passcode=passcode,
        recurrence=recurrence,
        includeType=False,
        includeQA=True,
    )
    resp = requests.patch(apiEndpointUrl, data=json.dumps(webinarDetails), headers=headers)
    if resp.status_code != 204 and "question_and_answer" in resp.text:
        webinarDetails = _webinarPayload(
            topic,
            startTime,
            duration,
            timezone=timezone,
            passcode=passcode,
            recurrence=recurrence,
            includeType=False,
            includeQA=False,
        )
        resp = requests.patch(
            apiEndpointUrl, data=json.dumps(webinarDetails), headers=headers
        )
    if resp.status_code != 204:
        raise RuntimeError(
            f"Zoom updateWebinar({webinarId}) failed: "
            f"HTTP {resp.status_code} {resp.text}"
        )
    return resp.status_code


def addPanelistsToWebinar(webinarId, panelistList):
    """
    panelistList: list of tuples (email, name). Zoom caps this endpoint at 30
    panelists per request, so longer lists are sent in chunks; returns the list
    of per-chunk API responses.
    """
    accessToken, _ = checkToken()
    apiEndpointUrl = f"https://api.zoom.us/v2/webinars/{webinarId}/panelists"
    headers = {
        "Authorization": f"Bearer {accessToken}",
        "content-type": "application/json",
    }
    responses = []
    for chunkStart in range(0, len(panelistList), 30):
        chunk = panelistList[chunkStart : chunkStart + 30]
        payload = {
            "panelists": [{"email": email, "name": name} for (email, name) in chunk]
        }
        resp = requests.post(apiEndpointUrl, data=json.dumps(payload), headers=headers)
        if resp.status_code not in (200, 201):
            raise RuntimeError(
                f"Zoom addPanelistsToWebinar({webinarId}) failed on panelists "
                f"{chunkStart}-{chunkStart + len(chunk) - 1}: "
                f"HTTP {resp.status_code} {resp.text}"
            )
        responses.append(resp.json())
    return responses


def getListOfPanelistsInWebinar(webinarId):
    accessToken, _ = checkToken()
    panelistList = []
    apiEndpointUrl = f"https://api.zoom.us/v2/webinars/{webinarId}/panelists"
    headers = {
        "Authorization": f"Bearer {accessToken}",
        "content-type": "application/json",
    }
    resp = requests.get(apiEndpointUrl, headers=headers)
    respJson = resp.json()
    if "panelists" not in respJson:
        raise RuntimeError(
            f"Zoom panelist list request for webinar {webinarId} failed: {respJson}"
        )
    for panelist in respJson["panelists"]:
        panelistList.append(
            (panelist["id"], panelist["name"], panelist["email"], panelist["join_url"])
        )
    return panelistList


def getListOfWebinars():
    webinars = _listPaginated("https://api.zoom.us/v2/users/me/webinars", "webinars")
    return [
        (webinar["id"], webinar["topic"], webinar.get("join_url"))
        for webinar in webinars
    ]


def deleteWebinar(webinarId):
    accessToken, _ = checkToken()
    apiEndpointUrl = f"https://api.zoom.us/v2/webinars/{webinarId}"
    headers = {
        "Authorization": f"Bearer {accessToken}",
        "content-type": "application/json",
    }
    resp = requests.delete(apiEndpointUrl, headers=headers)
    resp.raise_for_status()
    return resp.status_code


def deletePanelistFromWebinar(webinarId, panelistId):
    accessToken, _ = checkToken()
    apiEndpointUrl = (
        f"https://api.zoom.us/v2/webinars/{webinarId}/panelists/{panelistId}"
    )
    headers = {
        "Authorization": f"Bearer {accessToken}",
        "content-type": "application/json",
    }
    resp = requests.delete(apiEndpointUrl, headers=headers)
    resp.raise_for_status()
    return resp.status_code


######################################################################
########################## testing meetings ##########################
######################################################################
# print(getListOfMeetings())
# createZoomLinksIfNeeded("test_csv.csv", "topic", "zoom_link", "uid")
# print(doesMeetingExist("topic", "Opening Session"))
# deleteMeeting(meetingId)
