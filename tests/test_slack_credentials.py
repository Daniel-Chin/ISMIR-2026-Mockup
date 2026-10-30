"""Credential routing checks with no Slack API calls."""
import runpy
import sys

import pytest

from long_running_bots import announcement_bot
from utils import slack


@pytest.fixture(autouse=True)
def fake_credentials(monkeypatch):
    monkeypatch.setattr(announcement_bot, "load_dotenv", lambda **kwargs: None)
    for name in ("SLACK_BOT_TOKEN", "SLACK_USER_TOKEN", "SLACK_TOKEN_ANNOUNCEMENT_BOT"):
        monkeypatch.setenv(name, name + "-test")
    for name in ("client_bot", "client_user", "_channel_maps", "_user_maps"):
        monkeypatch.setattr(slack, name, getattr(slack, name))


@pytest.mark.parametrize("is_mockup", [False, True])
def test_workspace_credentials_and_cache_reset(monkeypatch, is_mockup):
    monkeypatch.setenv("DEPLOYMENT", "mockup" if is_mockup else "real")
    slack._channel_maps = ({"old": "COLD"}, {})
    slack._user_maps = ({"old": "UOLD"}, {})
    slack.configure_clients(is_mockup=is_mockup)
    assert slack.client_bot.token == "SLACK_BOT_TOKEN-test"
    assert slack.client_user.token == "SLACK_USER_TOKEN-test"
    assert slack._channel_maps is None
    assert slack._user_maps is None
    client = announcement_bot.create_slack_client(is_mockup=is_mockup)
    assert client.token == "SLACK_TOKEN_ANNOUNCEMENT_BOT-test"


@pytest.mark.parametrize("is_mockup", [False, True])
def test_mismatched_env_file_is_rejected(monkeypatch, is_mockup):
    monkeypatch.setenv("DEPLOYMENT", "real" if is_mockup else "mockup")
    with pytest.raises(SystemExit):
        slack.configure_clients(is_mockup=is_mockup)
    with pytest.raises(SystemExit):
        announcement_bot.create_slack_client(is_mockup=is_mockup)


@pytest.mark.parametrize("is_mockup", [False, True])
def test_prep_routes_event_description_credentials(monkeypatch, is_mockup):
    args = ["miniconf_prep.py", "--action", "set-event-channel-desc"]
    if is_mockup:
        args.append("--mockup")
    monkeypatch.setattr(sys, "argv", args)
    monkeypatch.setenv("DEPLOYMENT", "mockup" if is_mockup else "real")
    calls = []
    monkeypatch.setattr(slack, "batch_set_channel_description_interactive",
                        lambda path: calls.append((path, slack.client_bot.token)))
    runpy.run_module("miniconf_prep", run_name="__main__")
    assert calls == [("sitedata_mock" if is_mockup else "sitedata", "SLACK_BOT_TOKEN-test")]
