import pandas as pd
import pytest

from modules import tutorials as tutorials_module
from modules.tutorials import REGISTRATION_EMAIL, TUTORIAL_FEE_COLUMNS, Tutorials
from utils.identity import Person, SlackMember


class FakeSlack:
    def __init__(self):
        self.channels = {}
        self.created_public = []
        self.created_private = []
        self.invites = []
        self.reloads = 0

    def createSlackChannels(self, channel_names, *, is_private=False):
        created = self.created_private if is_private else self.created_public
        created.extend(channel_names)
        for index, name in enumerate(channel_names, start=1):
            self.channels[name] = f"C{index}"

    def loadAllChannelData(self):
        self.reloads += 1

    def getChannelID(self, channel_name):
        return self.channels.get(channel_name)

    def getChannelURL(self, channel_id):
        return f"https://ws.slack.com/archives/{channel_id}"

    def inviteUserToChannel(self, email, channel_name):
        self.invites.append((email, channel_name))


def write_events(path):
    pd.DataFrame(
        [
            {
                "uid": "1",
                "title": "Morning Tutorial",
                "category": "Tutorials",
                "slack_channel": "#tutorial-morning",
                "channel_url": "",
            },
            {
                "uid": "2",
                "title": "Afternoon Tutorial",
                "category": "Tutorials",
                "slack_channel": "tutorial-afternoon",
                "channel_url": "",
            },
            {
                "uid": "3",
                "title": "Opening",
                "category": "Opening",
                "slack_channel": "",
                "channel_url": "keep-me",
            },
        ]
    ).to_csv(path, index=False)


def write_registration(path):
    virtual, virtual_student, onsite, onsite_student = TUTORIAL_FEE_COLUMNS
    flags = {column: "0" for column in TUTORIAL_FEE_COLUMNS}
    pd.DataFrame(
        [
            {REGISTRATION_EMAIL: "virtual@example.com", **flags, virtual: "1"},
            {REGISTRATION_EMAIL: "Student@Example.com", **flags, onsite_student: "1"},
            {REGISTRATION_EMAIL: "preferred.elsewhere@example.com", **flags, onsite: "1"},
            {REGISTRATION_EMAIL: "no-slack@example.com", **flags, virtual_student: "1"},
            {REGISTRATION_EMAIL: "no-fee@example.com", **flags},
        ]
    ).to_csv(path, index=False)


class FakeInviteSlack:
    def __init__(self):
        self.added = []

    def addMemberIDsToChannel(self, channel, user_ids):
        self.added.append((channel, sorted(user_ids)))
        return sorted(user_ids)


def fake_members():
    def member(user_id, email):
        return SlackMember(user_id, Person.of(["Someone"], [email]))
    return (
        member("U1", "virtual@example.com"),
        member("U2", "student@example.com"),
        member("U3", "preferred@home.example"),
        member("U4", "no-fee@example.com"),
        member("U9", "dummy@example.com"),
    )


def test_create_tutorial_channels_private_and_write_links(tmp_path):
    events_path = tmp_path / "events.csv"
    write_events(events_path)
    slack = FakeSlack()

    Tutorials(events_path, None, useDummyValues=False).createSlackChannels(slack)

    assert slack.created_public == []
    assert slack.created_private == [
        "tutorial-morning",
        "tutorial-afternoon",
    ]
    assert slack.reloads == 1
    events = pd.read_csv(events_path).fillna("")
    assert events.loc[0, "channel_url"] == "https://ws.slack.com/archives/C1"
    assert events.loc[1, "channel_url"] == "https://ws.slack.com/archives/C2"
    assert events.loc[2, "channel_url"] == "keep-me"


def test_fee_payers_are_added_to_every_tutorial(tmp_path, monkeypatch):
    events_path = tmp_path / "events.csv"
    registration_path = tmp_path / "registration.csv"
    write_events(events_path)
    write_registration(registration_path)
    monkeypatch.setattr(tutorials_module, "slack_members", fake_members)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    slack = FakeInviteSlack()

    preferred = {"preferred.elsewhere@example.com": ["preferred@home.example"]}
    Tutorials(events_path, registration_path, False, preferred).addRegistrantsToChannels(slack)

    assert slack.added == [
        ("tutorial-morning", ["U1", "U2", "U3"]),
        ("tutorial-afternoon", ["U1", "U2", "U3"]),
    ]


def test_dummy_mode_adds_only_dummy_email(tmp_path, monkeypatch):
    events_path = tmp_path / "events.csv"
    registration_path = tmp_path / "registration.csv"
    write_events(events_path)
    write_registration(registration_path)
    monkeypatch.setenv("DUMMY_EMAIL", "dummy@example.com")
    monkeypatch.setattr(tutorials_module, "slack_members", fake_members)
    monkeypatch.setattr("builtins.input", lambda prompt: "y")
    slack = FakeInviteSlack()

    Tutorials(events_path, registration_path, useDummyValues=True).addRegistrantsToChannels(slack)

    assert slack.added == [("tutorial-morning", ["U9"]), ("tutorial-afternoon", ["U9"])]


def test_setup_names_preserves_other_category(tmp_path):
    from modules.events import Events

    path = tmp_path / "events.csv"
    write_events(path)
    events = pd.read_csv(path)
    events.loc[0, "title"] = "T1(M): LLMs x Music: Scalable Language Modeling"
    events.loc[2, "slack_channel"] = "existing-opening"
    events.to_csv(path, index=False)

    Tutorials(path, None, False).setupChannelNames()
    tutorials_named = pd.read_csv(path).fillna("")
    assert tutorials_named.loc[0, "slack_channel"] == "tutorial-t1-llms-x-music-scalable"
    assert tutorials_named.loc[2, "slack_channel"] == "existing-opening"

    Events(path, False).setupSlackChannels()
    events_named = pd.read_csv(path).fillna("")
    assert events_named.loc[:1, "slack_channel"].equals(tutorials_named.loc[:1, "slack_channel"])
    assert events_named.loc[2, "slack_channel"] == "opening"


def test_creation_filters_category_and_skips_blank_names(tmp_path):
    from modules.events import Events

    path = tmp_path / "events.csv"
    write_events(path)
    events = pd.read_csv(path)
    events.loc[1, "slack_channel"] = "   "
    events.loc[1, "channel_url"] = "keep-blank"
    events.loc[2, "slack_channel"] = "opening"
    events.to_csv(path, index=False)

    tutorial_slack = FakeSlack()
    Tutorials(path, None, False).createSlackChannels(tutorial_slack)
    assert tutorial_slack.created_public == []
    assert tutorial_slack.created_private == ["tutorial-morning"]
    assert tutorial_slack.invites == []
    after_tutorials = pd.read_csv(path).fillna("")
    assert after_tutorials.loc[1, "channel_url"] == "keep-blank"
    assert after_tutorials.loc[2, "channel_url"] == "keep-me"

    event_slack = FakeSlack()
    Events(path, False).createSlackChannels(event_slack)
    assert event_slack.created_public == ["opening"]
    assert event_slack.created_private == []
    after_events = pd.read_csv(path).fillna("")
    assert after_events.loc[:1, "channel_url"].equals(after_tutorials.loc[:1, "channel_url"])


def test_channel_creation_passes_privacy_to_slack_api(monkeypatch):
    from utils import slack

    calls = []

    class FakeClient:
        def conversations_create(self, **kwargs):
            calls.append(kwargs)
            return {"ok": True, "channel": {"name": kwargs["name"], "id": "C1"}}

    monkeypatch.setattr(slack, "client_bot", FakeClient())
    monkeypatch.setattr(slack, "_channel_maps", None)
    monkeypatch.setattr(slack, "isChannel", lambda name: name == "existing")
    slack.createSlackChannels(["tutorial", "existing"], is_private=True)
    slack.createSlackChannels(["opening"], is_private=False)
    assert calls == [
        {"name": "tutorial", "is_private": True},
        {"name": "opening", "is_private": False},
    ]


@pytest.mark.parametrize("dummy_mode", [False, True])
def test_add_admins_invites_before_next_prompt(tmp_path, monkeypatch, dummy_mode):
    path = tmp_path / "events.csv"
    write_events(path)
    slack = FakeSlack()
    responses = iter([
        ([], " first@example.org "),
        ([("first@example.org", "tutorial-morning"),
          ("first@example.org", "tutorial-afternoon")], "second@example.org"),
        ([("first@example.org", "tutorial-morning"),
          ("first@example.org", "tutorial-afternoon"),
          ("second@example.org", "tutorial-morning"),
          ("second@example.org", "tutorial-afternoon")], "   "),
    ])

    def prompt(_):
        expected, response = next(responses)
        assert slack.invites == expected
        return response

    monkeypatch.setattr("builtins.input", prompt)
    Tutorials(path, None, dummy_mode).addAdminsToChannels(slack)
    assert len(slack.invites) == 4


def test_add_admins_empty_input_does_nothing(tmp_path, monkeypatch):
    path = tmp_path / "events.csv"
    write_events(path)
    slack = FakeSlack()
    monkeypatch.setattr("builtins.input", lambda _: "")
    Tutorials(path, None, False).addAdminsToChannels(slack)
    assert slack.invites == []


def test_add_admins_stops_on_invitation_failure(tmp_path, monkeypatch):
    path = tmp_path / "events.csv"
    write_events(path)
    slack = FakeSlack()
    prompts = []

    def prompt(_):
        prompts.append(True)
        return "admin@example.org"

    def fail(*args):
        raise LookupError("member not found")

    monkeypatch.setattr("builtins.input", prompt)
    monkeypatch.setattr(slack, "inviteUserToChannel", fail)
    with pytest.raises(LookupError, match="member not found"):
        Tutorials(path, None, False).addAdminsToChannels(slack)
    assert len(prompts) == 1


def test_add_admins_cli_selects_mock_workspace(monkeypatch):
    import runpy
    from pathlib import Path
    from utils import slack

    calls = []
    monkeypatch.setattr("sys.argv", [
        "miniconf_prep.py", "--mockup", "--action", "add-admins-to-tutorials",
    ])
    monkeypatch.setattr(slack, "configure_clients", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(
        Tutorials, "addAdminsToChannels",
        lambda self, client: calls.append((self.eventsCsvFile, self.registrationCsvFile, client)),
    )
    runpy.run_path(str(Path(__file__).resolve().parents[1] / "miniconf_prep.py"), run_name="__main__")
    assert calls == [{"is_mockup": True}, ("sitedata_mock/events.csv", None, slack)]
