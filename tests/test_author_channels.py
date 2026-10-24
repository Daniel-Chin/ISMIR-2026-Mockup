from slack_sdk.errors import SlackApiError

from modules import author_channels
from modules.author_channels import Invite, plan_invites
from utils.identity import Person, Registrant, SlackMember

CMT = {"7": [("Zoe Lee", "zoe@uni.example"), ("Bo Park", "bo@uni.example")]}
CHANNELS = {"7": "p1-1-some-paper"}


def registrant(name, email, claimed=()):
    return Registrant(name, Person.of([name], [email]), frozenset(claimed), 0.0)


def member(user_id, name, email):
    return SlackMember(user_id, Person.of([name], [email]))


def test_plan_invites_sources():
    registrants = [
        registrant("Ray, Al", "al@home.example", claimed={"7"}),  # presenting for the authors
        registrant("Lee, Zoe", "zoe.home@home.example"),
        registrant("Park, Bo", "bo@uni.example"),  # not in Slack yet
    ]
    members = (
        member("U1", "Al", "al@home.example"),
        member("U2", "Zoe", "zoe.home@home.example"),
        member("U3", "Bo Park", "bo.park@elsewhere.example"),  # joined with an unknown email
        member("U4", "Amy Lee", "amy@uni.example"),
    )
    invites, not_in_slack = plan_invites(CHANNELS, CMT, registrants, members)
    assert {i.member.user_id: i.source for i in invites} == {
        "U1": "registration form: Ray, Al",
        "U2": "registrant name: Lee, Zoe",
        "U3": "Slack profile name",
    }
    assert not_in_slack == ["   7 p1-1-some-paper: Park, Bo (registrant email)"]


class FakeClient:
    def __init__(self, manager_error=None):
        self.invited, self.manager_calls, self.manager_error = [], [], manager_error

    def conversations_invite(self, channel, users, force):
        self.invited.append((channel, users))

    def api_call(self, method, json):
        self.manager_calls.append(json)
        if self.manager_error:
            raise SlackApiError("no", {"error": self.manager_error})


def test_apply_invites_adds_only_new_members_and_stops_manager_attempts(monkeypatch, tmp_path):
    monkeypatch.setattr(author_channels.slackUtils, "ADD_HISTORY_PATH", tmp_path / "history.json")
    bot, user = FakeClient(), FakeClient(manager_error="not_allowed_token_type")
    monkeypatch.setattr(author_channels.slackUtils, "client_bot", bot)
    monkeypatch.setattr(author_channels.slackUtils, "client_user", user)
    monkeypatch.setattr(author_channels.slackUtils, "getChannelID", lambda name: "C" + name)
    monkeypatch.setattr(author_channels.slackUtils, "memberIDsInChannel", lambda channel_id: ["U1"])
    m1, m2 = member("U1", "A", "a@x.example"), member("U2", "B", "b@x.example")
    author_channels.apply_invites([
        Invite("a", "1", m1, "s"), Invite("a", "1", m2, "s"), Invite("b", "2", m1, "s"),
    ])
    assert bot.invited == [("Ca", "U2")]
    assert user.manager_calls == [{"role_id": "Rl0A", "entity_ids": ["Ca"], "user_ids": ["U1", "U2"]}]


def test_add_history_keeps_out_whoever_left(monkeypatch, tmp_path):
    bot = FakeClient()
    members = {"U1"}
    monkeypatch.setattr(author_channels.slackUtils, "ADD_HISTORY_PATH", tmp_path / "history.json")
    monkeypatch.setattr(author_channels.slackUtils, "client_bot", bot)
    monkeypatch.setattr(author_channels.slackUtils, "getChannelID", lambda name: "C" + name)
    monkeypatch.setattr(author_channels.slackUtils, "memberIDsInChannel", lambda channel_id: sorted(members))
    add = author_channels.slackUtils.addMemberIDsToChannel
    assert add("a", {"U1", "U2"}) == ["U2"]
    members.clear()  # both quit: U1 was already in, U2 was added by us
    assert add("a", {"U1", "U2", "U3"}) == ["U3"]
    assert bot.invited == [("Ca", "U2"), ("Ca", "U3")]
