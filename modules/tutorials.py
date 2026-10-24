import os

import pandas as pd

from utils.identity import normalize_email, slack_members

REGISTRATION_EMAIL = "Email Address"
# One flag per fee variant; any nonzero one admits the registrant to every tutorial
TUTORIAL_FEE_COLUMNS = (
    "Virtual Tutorials (Full Day)",
    "Virtual Tutorials (Full Day) - Students",
    "Tutorials (Full Day)",
    "Tutorials (Full Day) - Students",
)


def getCleanTitle(incoming):
    return str(incoming).replace('"', "").replace("=", "").strip().lower()


class Tutorials:
    """Provision tutorial Slack channels and assign registered attendees."""

    def __init__(self, eventsCsvFile, registrationCsvFile, useDummyValues, preferredEmails=None):
        """preferredEmails: normalized registration email -> other emails, see utils.identity.load_preferred_emails"""
        self.eventsCsvFile = eventsCsvFile
        self.registrationCsvFile = registrationCsvFile
        self.preferredEmails = preferredEmails or {}
        self.useDummyValues = useDummyValues

    def _read_events(self):
        if self.eventsCsvFile is None:
            raise ValueError("eventsCsvFile is required")

        events = pd.read_csv(self.eventsCsvFile)
        required = {"category", "title", "slack_channel"}
        missing = required.difference(events.columns)
        if missing:
            raise ValueError(
                "events CSV is missing required columns: " + ", ".join(sorted(missing))
            )

        tutorial_mask = events["category"] == "Tutorials"
        tutorials = events.loc[tutorial_mask].copy()
        if tutorials.empty:
            raise ValueError("events CSV contains no Tutorials rows")
        if tutorials["slack_channel"].isna().any():
            raise ValueError("every tutorial needs a slack_channel value")

        return events, tutorial_mask, tutorials

    def setupChannelNames(self):
        from modules.events import Events

        Events(self.eventsCsvFile, self.useDummyValues, tutorials_only=True).setupSlackChannels()

    def createSlackChannels(self, slackUtils):
        """Create named private tutorial channels and write their links."""
        from modules.events import Events

        Events(self.eventsCsvFile, self.useDummyValues, tutorials_only=True).createSlackChannels(slackUtils)

    def addAdminsToChannels(self, slackUtils):
        """Add each entered Slack member to every tutorial channel."""
        channels = self._channels()
        while True:
            email = input("Admin email (empty to finish): ").strip()
            if not email:
                return
            for channel in channels:
                print(f"Adding admin {email} to channel {channel}")
                slackUtils.inviteUserToChannel(email, channel)

    def _channels(self):
        _, _, tutorials = self._read_events()
        channels = list(dict.fromkeys(
            str(name).strip().lstrip("#") for name in tutorials["slack_channel"]
        ))
        if any(not channel for channel in channels):
            raise ValueError("every tutorial needs a slack_channel value")
        return channels

    def _fee_payer_emails(self):
        """Registration emails of everyone who registered with the tutorial fee, payment status aside"""
        if self.registrationCsvFile is None:
            raise ValueError("registration CSV is required for attendee assignment")
        registration = pd.read_csv(self.registrationCsvFile, dtype=str, encoding="utf-8-sig").fillna("")
        missing = {REGISTRATION_EMAIL, *TUTORIAL_FEE_COLUMNS}.difference(registration.columns)
        if missing:
            raise ValueError(
                "registration CSV is missing required columns: " + ", ".join(sorted(missing))
            )
        flags = registration[list(TUTORIAL_FEE_COLUMNS)].apply(lambda column: pd.to_numeric(column).fillna(0))
        return [email.strip() for email in registration.loc[(flags > 0).any(axis=1), REGISTRATION_EMAIL] if email.strip()]

    def addRegistrantsToChannels(self, slackUtils):
        """Add everyone who registered with the tutorial fee to every tutorial channel; never removes anyone."""
        channels = self._channels()
        by_email = {email: member.user_id for member in slack_members() for email in member.person.emails}
        registrants = self._fee_payer_emails()

        user_ids, not_in_slack = set(), []
        for email in registrants:
            emails = [normalize_email(email), *map(normalize_email, self.preferredEmails.get(normalize_email(email), []))]
            found = {by_email[e] for e in emails if e in by_email}
            if not found:
                not_in_slack.append(email)
            user_ids |= found
        print(f"{len(registrants)} registered with the tutorial fee; {len(user_ids)} Slack members to add.")
        if not_in_slack:
            print(f"Not in Slack yet ({len(not_in_slack)}): {', '.join(sorted(not_in_slack))}")

        if self.useDummyValues:
            dummy_email = normalize_email(os.environ.get("DUMMY_EMAIL", "default_dummy_email@example.com"))
            if dummy_email not in by_email:
                raise LookupError(f"DUMMY_EMAIL {dummy_email} is not a member of the workspace")
            user_ids = {by_email[dummy_email]}
            print(f"Not --prod: only {dummy_email} is added instead.")

        if input(f"Add {len(user_ids)} members to {len(channels)} tutorial channels? [y/N] ").strip().lower() != "y":
            return
        for channel in channels:
            added = slackUtils.addMemberIDsToChannel(channel, user_ids)
            print(f"{channel}: added {len(added)}")
