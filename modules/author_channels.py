"""
Invites authors into their paper and LBD channels, and tries to make them channel managers.

A Slack member counts as an author of channel X (for CMT ID X) if any of these holds, first match wins in the log:
1. they registered with, or gave as preferred email, the email of a registrant who typed X into the registration form
2. same, for a registrant whom utils.identity matches to one of X's CMT authors (weak evidence included)
3. utils.identity matches their Slack profile to one of X's CMT authors directly (weak evidence included)
Workspace invitations only go to registration emails and preferred emails, so 1 and 2 cover everyone whose
preferred email is known; 3 is the safety net. False positives cost little in public channels.
"""

import csv
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

from slack_sdk.errors import SlackApiError

from utils import slack as slackUtils
from utils.identity import (
    Person, Registrant, SlackMember, load_cmt_authors, load_preferred_emails, load_registrants, match_evidence,
    normalize_email, slack_members,
)

# Built-in role ID of channel managers in admin.roles.addAssignments
CHANNEL_MANAGER_ROLE = "Rl0A"
PLAN_PATH = Path("tmp/author_channel_invites.csv")
EVIDENCE_ORDER = ("email", "name", "related + partial name", "name variant", "email resembles name", "similar email")


@dataclass(frozen=True)
class Invite:
    channel: str
    cmt_id: str
    member: SlackMember
    source: str


def load_channels(data_path: str) -> dict[str, str]:
    """CMT ID -> Slack channel name, for papers and LBDs"""
    channels = {}
    for name in ("papers.csv", "lbds.csv"):
        with open(os.path.join(data_path, name), newline="", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if channel := row["slack_channel"].strip().lstrip("#"):
                    if row["uid"] in channels:
                        raise ValueError(f"CMT ID {row['uid']} has two channels")
                    channels[row["uid"]] = channel
    return channels


def _best_evidence(authors: list[Person], person: Person) -> str | None:
    found = [e for author in authors if (e := match_evidence(author, person))]
    return min(found, key=EVIDENCE_ORDER.index, default=None)


def plan_invites(
    channels: dict[str, str],
    cmt: dict[str, list[tuple[str, str]]],
    registrants: list[Registrant],
    members: tuple[SlackMember, ...],
) -> tuple[list[Invite], list[str]]:
    """Returns the invites and notes about registered authors who have no Slack account yet."""
    by_email = {email: member for member in members for email in member.person.emails}
    invites, not_in_slack = [], []
    for cmt_id, channel in channels.items():
        if cmt_id not in cmt:
            print(f"Warning: CMT ID {cmt_id} ({channel}) is not in the CMT export")
        authors = [Person.of([name], [email]) for name, email in cmt.get(cmt_id, [])]
        chosen: dict[str, Invite] = {}
        for registrant in registrants:
            if cmt_id in registrant.claimed_papers:
                source = "registration form"
            elif evidence := _best_evidence(authors, registrant.person):
                source = f"registrant {evidence}"
            else:
                continue
            reached = [by_email[e] for e in sorted(registrant.person.emails) if e in by_email]
            if not reached:
                not_in_slack.append(f"{cmt_id:>4} {channel}: {registrant.name} ({source})")
            for member in reached:
                chosen.setdefault(member.user_id, Invite(channel, cmt_id, member, f"{source}: {registrant.name}"))
        for member in members:
            if evidence := _best_evidence(authors, member.person):
                chosen.setdefault(member.user_id, Invite(channel, cmt_id, member, f"Slack profile {evidence}"))
        invites += chosen.values()
    return invites, not_in_slack


def write_plan(invites: list[Invite], path: Path = PLAN_PATH) -> None:
    path.parent.mkdir(exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["channel", "cmt_id", "slack_user_id", "slack_names", "slack_emails", "source"])
        for i in invites:
            writer.writerow([i.channel, i.cmt_id, i.member.user_id, "; ".join(sorted(i.member.person.names)),
                             "; ".join(sorted(i.member.person.emails)), i.source])


def apply_invites(invites: list[Invite]) -> None:
    """Adds everyone to their channels (never removes) and tries to make them channel managers."""
    by_channel: dict[str, set[str]] = defaultdict(set)
    for i in invites:
        by_channel[i.channel].add(i.member.user_id)
    can_assign_managers = True
    for channel, user_ids in by_channel.items():
        channel_id = slackUtils.getChannelID(channel)
        if channel_id is None:
            print(f"{channel}: channel not found, skipped")
            continue
        new = sorted(user_ids - set(slackUtils.memberIDsInChannel(channel_id)))
        if new:
            try:
                # force: still add the valid users if some of them can't be added
                slackUtils.client_bot.conversations_invite(channel=channel_id, users=",".join(new), force=True)
                print(f"{channel}: added {len(new)}")
            except SlackApiError as e:
                print(f"{channel}: adding {new} failed: {e.response['error']}")
        if can_assign_managers:
            try:
                slackUtils.client_user.api_call("admin.roles.addAssignments", json={
                    "role_id": CHANNEL_MANAGER_ROLE, "entity_ids": [channel_id], "user_ids": sorted(user_ids)})
            except SlackApiError as e:
                print(f"Channel managers can't be assigned through the API ({e.response['error']}); "
                      f"set them by hand from {PLAN_PATH} if needed.")
                can_assign_managers = False


def invite_authors_to_channels(
    data_path: str,
    cmt_csv: str,
    registration_csv: str,
    preferred_emails_csv: str | None,
    use_dummy_values: bool,
) -> None:
    channels = load_channels(data_path)
    preferred = load_preferred_emails(Path(preferred_emails_csv)) if preferred_emails_csv else None
    registrants = load_registrants(Path(registration_csv), preferred)
    members = slack_members()
    invites, not_in_slack = plan_invites(channels, load_cmt_authors(Path(cmt_csv)), registrants, members)
    write_plan(invites)

    print(f"{len(invites)} invites over {len({i.channel for i in invites})}/{len(channels)} channels; "
          f"plan written to {PLAN_PATH}")
    for source, n in Counter(i.source.split(":")[0] for i in invites).most_common():
        print(f"  {n:>5}  {source}")
    if empty := sorted(set(channels.values()) - {i.channel for i in invites}):
        print(f"Channels without any author in Slack ({len(empty)}): {', '.join(empty)}")
    if not_in_slack:
        print(f"Registered authors not in Slack yet ({len(not_in_slack)}):")
        print("\n".join(f"  {line}" for line in not_in_slack))

    if use_dummy_values:
        dummy_email = normalize_email(os.environ.get("DUMMY_EMAIL", "default_dummy_email@example.com"))
        dummy = next((m for m in members if dummy_email in m.person.emails), None)
        if dummy is None:
            raise LookupError(f"DUMMY_EMAIL {dummy_email} is not a member of the workspace")
        invites = [Invite(channel, cmt_id, dummy, "dummy") for cmt_id, channel in channels.items()]
        print(f"Not --prod: every channel gets only {dummy_email} instead.")

    if input(f"Add {len(invites)} members to channels and make them channel managers? [y/N] ").strip().lower() != "y":
        return
    apply_invites(invites)
