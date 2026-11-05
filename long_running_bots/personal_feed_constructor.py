"""
Personal Feed Constructor: each evening, silently adds opted-in members to the
Slack channels of the next day's events, filtered by the categories they chose.

Pacing is the point: the bot's only advertisement is one DM per member. Members
who have caught up on their unreads may open it and ask for more content.

Flow (all in the bot's DM):
- Greeting with an opt-in button. Sent once to every full member (not guests,
  bots or deactivated accounts) at startup, and to members who join later.
  With --email, greets only that member (e.g. to try the bot on yourself).
- Opt in -> category checkboxes (some ticked by default) + Save + Stop.
- Save -> if channels for events before the next round are available, asks
  whether to add the member now. Then: "Find me again to reconfigure your feed!"
- Any DM to the bot shows the checkboxes again, pre-filled with saved choices.

Adding is silent: Slack's own "added by" system message is the only trace.
The bot never re-adds a member to a channel it added them to before, so leaving
a channel sticks.

One-time Slack app setup:
- https://api.slack.com/apps?new_app=1 -> new blank app "Personal Feed Constructor".
- Enable Socket Mode; generate an app-level token with connections:write.
- Bot Token Scopes: chat:write im:write im:history channels:join channels:manage
  channels:read users:read users:read.email
- Event Subscriptions -> bot events: message.im team_join
- Interactivity: on (Socket Mode needs no request URL).
- App Home: enable the Messages tab and "Allow users to send messages".
- Workspace admin: allow apps to add people to channels.
- Install to the workspace, then put in the repository's .env:
    SLACK_BOT_TOKEN_FEED_CONSTRUCTOR=xoxb-...
    SLACK_APP_TOKEN_FEED_CONSTRUCTOR=xapp-...

Run from the repository root:
uv run python -m long_running_bots.personal_feed_constructor [--email you@example.com]

State (greeted members, preferences, invites made) persists in tmp/, so
restarting is safe. A missed evening round runs on the next startup, for the
events that have not ended yet. Loads events.csv once; restart after editing it.
"""

import argparse
import json
import logging
import os
import ssl
from dataclasses import dataclass
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path
from threading import Event, RLock, Thread
from typing import Any

import certifi
import pandas as pd
from dotenv import load_dotenv
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError
from slack_sdk.http_retry.builtin_handlers import RateLimitErrorRetryHandler
from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.client import BaseSocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse

from utils.shared import load_conference_timezone

# These constants should be changed per conference.
SITE_DATA_PATH = "sitedata"
CITY = "Abu Dhabi"
ROUND_AT = dtime(20, 0)  # conference-local time of the evening round

STATE_PATH = Path("tmp/personal_feed_constructor_state.json")
CHECK_INTERVAL_SECONDS = 30
INVITE_BATCH = 1000  # Slack's max users per conversations.invite
# Failures that concern the users, not the channel: retrying would not help.
SETTLED_INVITE_ERRORS = {
    "already_in_channel", "cant_invite_self", "user_is_restricted",
    "ura_max_channels", "user_not_found", "cant_invite",
}

# (option value, label, events.csv categories, ticked by default). Slack allows at most 10.
CATEGORY_OPTIONS = [
    ("award", "★ Award nominee sessions", {"Award nominee"}, True),
    ("keynote", "Keynotes", {"All Meeting"}, True),
    ("oral", "Oral sessions", {"Oral session"}, True),
    ("poster", "Poster sessions", {"Poster session"}, True),
    ("special", "Special sessions", {"Special"}, False),
    ("majlis", "Majlis", {"Majlis"}, False),
]
NOT_OFFERED = {
    "Tutorials", "Music", "Social", "Opening", "Awards", "Industry", "WiMIR Meetup",
    "Meetup", "Unconference", "Registration", "Lunch", "LBD",
}
DEFAULT_KEYS = [key for key, _, _, ticked in CATEGORY_OPTIONS if ticked]
LABELS = {key: label for key, label, _, _ in CATEGORY_OPTIONS}
KEY_OF_CATEGORY = {cat: key for key, _, cats, _ in CATEGORY_OPTIONS for cat in cats}

GREETING = (
    "Not sure what channels to join? Too lazy to manually join channels? "
    "I can add you to popular channels periodically."
)
CONFIG_PROMPT = (
    f"Each evening in {CITY} time, I will add you to channels related to the next day's "
    "conference. What suits your appetite?"
)
FAREWELL = "Find me again to reconfigure your feed!"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FeedEvent:
    title: str
    key: str  # category option value
    channel_id: str
    day: date
    end_at: datetime


def load_events(tz: Any) -> list[FeedEvent]:
    csv_data = pd.read_csv(Path(SITE_DATA_PATH) / "events.csv", dtype=str).fillna("")
    events = []
    for _, row in csv_data.iterrows():
        channel_id = row["channel_url"].strip().rstrip("/").rsplit("/", 1)[-1]
        if not channel_id:
            continue
        category = row["category"].strip()
        key = KEY_OF_CATEGORY.get(category)
        if key is None:
            if category not in NOT_OFFERED:
                logger.warning("Category %r of %r is not offered; edit CATEGORY_OPTIONS.", category, row["title"])
            continue
        day = date.fromisoformat(row["start_date"].strip())
        hour, minute = map(int, row["end_time"].strip().split(":")[:2])
        events.append(FeedEvent(
            title=row["title"].strip(), key=key, channel_id=channel_id, day=day,
            end_at=datetime.combine(day, dtime(hour, minute), tzinfo=tz),
        ))
    return events


class State:
    """Persisted. `prefs[user]` is None once the user stops the feed."""

    def __init__(self) -> None:
        data = json.loads(STATE_PATH.read_text()) if STATE_PATH.exists() else {}
        self.greeted: set[str] = set(data.get("greeted", []))
        self.prefs: dict[str, list[str] | None] = data.get("prefs", {})
        self.invited: dict[str, set[str]] = {u: set(c) for u, c in data.get("invited", {}).items()}
        last = data.get("last_round_day")
        self.last_round_day: date | None = date.fromisoformat(last) if last else None

    def save(self) -> None:
        STATE_PATH.parent.mkdir(exist_ok=True)
        tmp = STATE_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps({
            "greeted": sorted(self.greeted),
            "prefs": self.prefs,
            "invited": {u: sorted(c) for u, c in self.invited.items()},
            "last_round_day": self.last_round_day.isoformat() if self.last_round_day else None,
        }, indent=1))
        tmp.replace(STATE_PATH)


def section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def button(text: str, action_id: str, style: str | None = None) -> dict:
    b = {"type": "button", "text": {"type": "plain_text", "text": text}, "action_id": action_id}
    if style:
        b["style"] = style
    return b


def option(key: str) -> dict:
    return {"text": {"type": "plain_text", "text": LABELS[key]}, "value": key}


def greeting_blocks() -> list[dict]:
    return [section(GREETING), {"type": "actions", "elements": [button("Opt me in", "opt_in", "primary")]}]


def config_blocks(selected: list[str]) -> list[dict]:
    checkboxes = {
        "type": "checkboxes", "action_id": "categories",
        "options": [option(key) for key, _, _, _ in CATEGORY_OPTIONS],
    }
    if selected:
        checkboxes["initial_options"] = [option(key) for key in selected if key in LABELS]
    return [
        section(CONFIG_PROMPT),
        {"type": "actions", "block_id": "categories", "elements": [checkboxes]},
        {"type": "actions", "elements": [
            button("Save", "save_prefs", "primary"), button("Stop my feed", "opt_out"),
        ]},
    ]


def selected_keys(payload: dict) -> list[str]:
    value = payload.get("state", {}).get("values", {}).get("categories", {}).get("categories", {})
    return [o["value"] for o in value.get("selected_options") or []]


class FeedConstructor:
    def __init__(self, client: WebClient, only_user: str | None = None) -> None:
        self.client = client
        self.only_user = only_user  # user ID; if set, greet nobody else
        self.tz = load_conference_timezone(SITE_DATA_PATH)
        self.events = load_events(self.tz)
        self.state = State()
        self.lock = RLock()
        self.joined_channels: set[str] = set()

    def now(self) -> datetime:
        return datetime.now(self.tz)

    # ---- inviting ----

    def invite(self, channel_id: str, users: list[str]) -> list[str]:
        """Return users whose invite is settled (added, or failed for a per-user reason)."""
        if channel_id not in self.joined_channels:
            self.client.conversations_join(channel=channel_id)
            self.joined_channels.add(channel_id)
        settled = []
        for i in range(0, len(users), INVITE_BATCH):
            batch = users[i:i + INVITE_BATCH]
            try:
                response = self.client.conversations_invite(channel=channel_id, users=",".join(batch), force=True)
                for error in response.get("errors", []):
                    if error.get("error") not in SETTLED_INVITE_ERRORS:
                        logger.warning("Invite %s to %s: %s", error.get("user"), channel_id, error.get("error"))
                settled += batch
            except SlackApiError as e:
                if e.response.get("error") in SETTLED_INVITE_ERRORS:
                    settled += batch
                else:
                    logger.error("Invite to %s failed: %s", channel_id, e.response.get("error"))
        return settled

    def run_invites(self, plan: dict[str, list[str]]) -> int:
        """plan: channel -> users. Records settled invites. Returns the number of settled pairs."""
        count = 0
        for channel_id, users in plan.items():
            try:
                settled = self.invite(channel_id, users)
            except SlackApiError as e:
                logger.error("Could not join %s: %s", channel_id, e.response.get("error"))
                continue
            with self.lock:
                for user in settled:
                    self.state.invited.setdefault(user, set()).add(channel_id)
                self.state.save()
            count += len(settled)
        return count

    def wanted_channels(self, user: str, days: set[date] | None, until: date | None = None) -> list[str]:
        """Channels of upcoming events the user wants and was never added to by this bot."""
        keys = set(self.state.prefs.get(user) or [])
        done = self.state.invited.get(user, set())
        now = self.now()
        channels = []
        for e in self.events:
            in_range = (e.day in days) if days is not None else (until is not None and e.day <= until)
            if in_range and e.key in keys and e.end_at > now and e.channel_id not in done \
                    and e.channel_id not in channels:
                channels.append(e.channel_id)
        return channels

    def round_target(self) -> date:
        now = self.now()
        return now.date() + timedelta(days=1) if now.time() >= ROUND_AT else now.date()

    def evening_round(self) -> None:
        target = self.round_target()
        with self.lock:
            if self.state.last_round_day is not None and self.state.last_round_day >= target:
                return
            plan: dict[str, list[str]] = {}
            for user, keys in self.state.prefs.items():
                if keys:
                    for channel_id in self.wanted_channels(user, {target}):
                        plan.setdefault(channel_id, []).append(user)
        logger.info("Round for %s: %d channels", target, len(plan))
        count = self.run_invites(plan)
        with self.lock:
            self.state.last_round_day = target
            self.state.save()
        logger.info("Round for %s done: %d additions", target, count)

    def scheduler(self) -> None:
        while True:
            try:
                self.evening_round()
            except Exception:
                logger.exception("Evening round failed; retrying")
            Event().wait(CHECK_INTERVAL_SECONDS)

    # ---- greeting ----

    def greet(self, user: dict) -> None:
        if user.get("is_bot") or user.get("deleted") or user.get("id") == "USLACKBOT" \
                or user.get("is_restricted") or user.get("is_ultra_restricted"):
            return
        user_id = user["id"]
        with self.lock:
            if user_id in self.state.greeted:
                return
        self.client.chat_postMessage(channel=user_id, text=GREETING, blocks=greeting_blocks())
        with self.lock:
            self.state.greeted.add(user_id)
            self.state.save()

    def greet_everyone(self) -> None:
        if self.only_user:
            self.greet(self.client.users_info(user=self.only_user)["user"])
            return
        for page in self.client.users_list(limit=200):
            for user in page["members"]:
                try:
                    self.greet(user)
                except SlackApiError as e:
                    logger.error("Could not greet %s: %s", user.get("id"), e.response.get("error"))
        logger.info("Greeted members: %d", len(self.state.greeted))

    # ---- conversation ----

    def show_config(self, user: str, channel: str, ts: str | None = None) -> None:
        with self.lock:
            saved = self.state.prefs.get(user)
        blocks = config_blocks(saved if saved else DEFAULT_KEYS)
        if ts:
            self.client.chat_update(channel=channel, ts=ts, text=CONFIG_PROMPT, blocks=blocks)
        else:
            self.client.chat_postMessage(channel=channel, text=CONFIG_PROMPT, blocks=blocks)

    def head_start_channels(self, user: str) -> list[str]:
        """Channels the latest round already covered, which this user has not got."""
        with self.lock:
            covered = self.state.last_round_day
            return self.wanted_channels(user, None, until=covered) if covered else []

    def on_action(self, payload: dict) -> None:
        action = payload["actions"][0]["action_id"]
        user = payload["user"]["id"]
        channel = payload["container"]["channel_id"]
        ts = payload["container"]["message_ts"]

        def finish(text: str) -> None:
            self.client.chat_update(channel=channel, ts=ts, text=text, blocks=[section(text)])

        if action == "opt_in":
            self.show_config(user, channel, ts)
        elif action == "save_prefs":
            keys = selected_keys(payload)
            with self.lock:
                self.state.prefs[user] = keys
                self.state.save()
            if not keys:
                finish(f"Nothing ticked, so I won't add you anywhere. {FAREWELL}")
                return
            summary = "Saved: " + ", ".join(LABELS[k] for k in keys) + "."
            pending = self.head_start_channels(user)
            if not pending:
                finish(f"{summary}\n{FAREWELL}")
                return
            question = (
                f"{summary}\nWant a head start? I can add you now to {len(pending)} "
                f"channel{'s' if len(pending) > 1 else ''} for events before my next round "
                f"({ROUND_AT:%H:%M} {CITY} time)."
            )
            self.client.chat_update(channel=channel, ts=ts, text=question, blocks=[
                section(question),
                {"type": "actions", "elements": [
                    button("Add me now", "head_start", "primary"), button("Wait for the next round", "wait"),
                ]},
            ])
        elif action == "head_start":
            finish(f"On it.\n{FAREWELL}")
            self.run_invites({c: [user] for c in self.head_start_channels(user)})
        elif action == "wait":
            finish(f"See you at the next round.\n{FAREWELL}")
        elif action == "opt_out":
            with self.lock:
                self.state.prefs[user] = None
                self.state.save()
            finish("Feed stopped. You stay in the channels you already have. Find me again to restart it!")
        # "categories" (a checkbox toggle) needs no reply.

    def on_event(self, event: dict) -> None:
        if event.get("type") == "team_join" and not self.only_user:
            self.greet(event["user"])
        elif event.get("type") == "message" and event.get("channel_type") == "im" \
                and not event.get("subtype") and not event.get("bot_id") and event.get("user"):
            self.show_config(event["user"], event["channel"])

    def handle_request(self, client: BaseSocketModeClient, request: SocketModeRequest) -> None:
        client.send_socket_mode_response(SocketModeResponse(envelope_id=request.envelope_id))
        try:
            if request.type == "interactive" and request.payload.get("type") == "block_actions":
                self.on_action(request.payload)
            elif request.type == "events_api":
                self.on_event(request.payload["event"])
        except Exception:
            logger.exception("Failed to handle %s", request.type)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", help="Greet only this member instead of all members (needs users:read.email).")
    args = parser.parse_args()
    load_dotenv()
    bot_token = os.environ.get("SLACK_BOT_TOKEN_FEED_CONSTRUCTOR", "").strip()
    app_token = os.environ.get("SLACK_APP_TOKEN_FEED_CONSTRUCTOR", "").strip()
    assert bot_token
    assert app_token

    web_client = WebClient(token=bot_token, ssl=ssl.create_default_context(cafile=certifi.where()))
    web_client.retry_handlers.append(RateLimitErrorRetryHandler(max_retry_count=5))
    only_user = web_client.users_lookupByEmail(email=args.email)["user"]["id"] if args.email else None
    bot = FeedConstructor(web_client, only_user)
    client = SocketModeClient(app_token=app_token, web_client=web_client)
    client.socket_mode_request_listeners.append(bot.handle_request)
    try:
        client.connect()
        Thread(target=bot.greet_everyone, name="greet", daemon=True).start()
        Thread(target=bot.scheduler, name="scheduler", daemon=True).start()
        logger.info("Personal Feed Constructor running")
        Event().wait()
    except KeyboardInterrupt:
        logger.info("Stopping Personal Feed Constructor")
    finally:
        client.close()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
