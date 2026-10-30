"""
Posts and pins the miniconf URL listing each poster session's papers to that session's Slack channel.
uv run python -m scripts.post_miniconf_url_to_poster_channels --dry-run
"""

import argparse
import csv
import re

from slack_sdk.errors import SlackApiError

from utils import slack
from utils.shared import load_site_config

SITEDATA_DIR = './sitedata'
EVENTS_CSV = f'{SITEDATA_DIR}/events.csv'


def iter_poster_sessions():
    '''Yield (poster_session_i, slack_channel) for each poster session in events.csv.'''
    with open(EVENTS_CSV, 'r', encoding='utf-8') as f:
        for row in csv.DictReader(f):
            if row['category'].strip().lower() != 'poster session':
                continue
            match = re.fullmatch(r'Poster Session - (\d+)', row['title'].strip())
            if match is None:
                raise ValueError(f'Cannot parse poster session index from title: {row["title"]!r}')
            yield int(match.group(1)), row['slack_channel'].strip().lstrip('#')


def render(miniconf_url: str, poster_session_i: int) -> str:
    url = f'{miniconf_url.rstrip("/")}/papers.html?session={poster_session_i}'
    return f'Browse the papers of Poster Session {poster_session_i}: <{url}>'


def find_posted_message_ts(channel_id: str, message: str) -> str | None:
    '''Timestamp of the bot's earlier post of `message` in the channel, if any.'''
    bot_user_id = slack.client_bot.auth_test()['user_id']
    for page in slack.client_bot.conversations_history(channel=channel_id, limit=slack.PAGE_LIMIT):
        for m in page.get('messages') or []:
            if m.get('user') == bot_user_id and m.get('text') == message:
                return m['ts']
    return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dry-run', action='store_true', help='Print messages without posting.')
    parser.add_argument('--mockup', action='store_true', help='Use the mockup workspace. Requires mockup.env to be loaded.')
    args = parser.parse_args()

    slack.configure_clients(is_mockup=args.mockup)
    miniconf_url = load_site_config(SITEDATA_DIR)['miniconf_url']

    for poster_session_i, channel_name in iter_poster_sessions():
        message = render(miniconf_url, poster_session_i)
        print(f'#{channel_name}: {message}')
        if args.dry_run:
            continue
        channel_id = slack.getChannelID(channel_name)
        if channel_id is None:
            raise LookupError(f'Channel {channel_name} does not exist in the workspace.')
        # The bot must be a channel member to post.
        slack.client_bot.conversations_join(channel=channel_id)
        ts = find_posted_message_ts(channel_id, message)
        if ts is None:
            ts = slack.client_bot.chat_postMessage(channel=channel_id, text=message)['ts']
        else:
            print('  Already posted; not reposting.')
        # pins.add requires the pins:write bot scope.
        try:
            slack.client_bot.pins_add(channel=channel_id, timestamp=ts)
        except SlackApiError as e:
            if e.response['error'] != 'already_pinned':
                raise
            print('  Already pinned.')


if __name__ == '__main__':
    main()
