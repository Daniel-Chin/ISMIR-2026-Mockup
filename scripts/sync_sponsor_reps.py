"""Check the Warm-up's sponsor reps tab: who each email is in Slack, and any problems.

The Worker reads the tab itself (preconf/src/auth.js sheetReps) and looks the emails up with its
own Slack bot token; this script is the local preview of what it will find. Read-only.

The tab (Live Database, the spreadsheet of PAPERS_SHEET_URL, tab TAB_GID; link-readable, so no
login) has one row per sponsor: the sponsor, then its reps' emails, one per column, as many as
needed. The sponsor is its id or name on the Warm-up (preconf/public/data/program.json's
sponsors: moises, adobe, anghami; "Adobe Research" works too). A row starting with "admin" lists
moderators instead. A header row is optional.

    python scripts/sync_sponsor_reps.py            # print who is who
    python scripts/sync_sponsor_reps.py --json F   # also write what the Worker would build

The Worker takes a sponsor's id from the first word of the row (it has no sponsor names), so keep
that word the Warm-up id: "moises", "adobe research", "anghami".
"""
import argparse
import csv
import io
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

import dotenv
from slack_sdk.errors import SlackApiError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from utils import slack  # noqa: E402

TAB_GID = '1376701259'
EMAIL = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


def read_tab() -> list[list[str]]:
    dotenv.load_dotenv(ROOT / '.env')
    match = re.search(r'/spreadsheets/d/([\w-]+)', os.environ.get('PAPERS_SHEET_URL', ''))
    if not match:
        raise SystemExit('PAPERS_SHEET_URL is not set')
    url = f'https://docs.google.com/spreadsheets/d/{match.group(1)}/export?format=csv&gid={TAB_GID}'
    with urllib.request.urlopen(url) as res:
        grid = list(csv.reader(io.StringIO(res.read().decode('utf-8'))))
    rows = [[c.strip() for c in line] for line in grid if any(c.strip() for c in line)]
    if rows and not any(EMAIL.match(c) for c in rows[0][1:]) and any('email' in c.lower() or 'sponsor' in c.lower() for c in rows[0]):
        rows = rows[1:]   # a header row
    return rows


def sponsor_id(text: str, sponsors: dict) -> str | None:
    """'moises', 'Moises' or 'Adobe Research' -> the Warm-up id (moises, adobe)."""
    t = text.strip().lower()
    for sid, name in sponsors.items():
        if t in (sid, name.lower()) or t.split()[:1] == [sid] or t.startswith(name.lower() + ' '):
            return sid
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    ap.add_argument('--json', type=Path, help='also write the Slack ids here, as the Worker builds them')
    args = ap.parse_args()
    program = json.loads((ROOT / 'preconf/public/data/program.json').read_text(encoding='utf-8'))
    sponsors = {s['id']: s['name'] for s in program.get('sponsors', [])}
    slack.configure_clients(os.environ.get('DEPLOYMENT') == 'mockup')
    out = {'sponsors': {}, 'admins': []}
    problems = []
    for row in read_tab():
        head, emails = row[0], [e.lower() for e in row[1:] if e]
        role = 'admin' if head.lower() in ('admin', 'admins', 'moderator', 'moderators') else sponsor_id(head, sponsors)
        if not role:
            problems.append(f'unknown sponsor {head!r}; Warm-up sponsors: {", ".join(sorted(sponsors))}')
            continue
        if role != 'admin':
            out['sponsors'].setdefault(role, [])
        if not emails:
            print(f'{role:10} (no contact yet)')
        for email in emails:
            if not EMAIL.match(email):
                problems.append(f'{role}: not an email: {email!r}')
                continue
            try:
                user = slack.client_bot.users_lookupByEmail(email=email)['user']
            except SlackApiError as e:
                problems.append(f'{role}: {email} not in Slack ({e.response["error"]})')
                continue
            print(f'{role:10} {email:40} {user["id"]}  {user.get("real_name", "")}')
            ids = out['admins'] if role == 'admin' else out['sponsors'][role]
            if user['id'] not in ids:
                ids.append(user['id'])
    for p in problems:
        print('PROBLEM', p)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(out, indent=1) + '\n', encoding='utf-8')
        print(f'-> {args.json}')


if __name__ == '__main__':
    main()
