"""
Writes cells of the Live Database papers tab (PAPERS_SHEET_URL in .env) through the Google Sheets API.
Every change is printed first and written only after confirmation, and only if the sheet still holds
the value it is replacing (else: pull_from_google_sheet.py, and rerun).
Needs env vars google_client_id and google_client_secret, and the Sheets API enabled in their project.
"""

import os
import re
from dataclasses import dataclass
from pathlib import Path

import dotenv

ROOT = Path(__file__).resolve().parent.parent
SHEETS_SCOPE = 'https://www.googleapis.com/auth/spreadsheets'
SHOWN_CHARS = 200


@dataclass(frozen=True)
class CellChange:
    uid: str
    column: str
    before: str
    after: str


def google_credentials(scopes: list[str]):
    """After a browser login; the URL is printed, as WSL has no browser to open."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    dotenv.load_dotenv(ROOT / '.env')
    client_id = os.environ.get('google_client_id')
    client_secret = os.environ.get('google_client_secret')
    if not client_id or not client_secret:
        raise SystemExit('Set env vars google_client_id and google_client_secret')
    flow = InstalledAppFlow.from_client_config({'installed': {
        'client_id': client_id,
        'client_secret': client_secret,
        'auth_uri': 'https://accounts.google.com/o/oauth2/auth',
        'token_uri': 'https://oauth2.googleapis.com/token',
    }}, scopes)
    return flow.run_local_server(port=0, open_browser=False)


def column_letter(index: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA."""
    letters = ''
    index += 1
    while index:
        index, rest = divmod(index - 1, 26)
        letters = chr(ord('A') + rest) + letters
    return letters


def shown(value: str) -> str:
    return repr(value if len(value) <= SHOWN_CHARS else value[:SHOWN_CHARS] + '…')


def update_papers_tab(changes: list[CellChange], credentials) -> bool:
    """Print the changes, ask, write them, and read them back. True when written."""
    from googleapiclient.discovery import build

    if not changes:
        print('Live Database: nothing to update.')
        return False
    dotenv.load_dotenv(ROOT / '.env')
    url = os.environ.get('PAPERS_SHEET_URL', '')
    match = re.search(r'/spreadsheets/d/([\w-]+)', url)
    gid = re.search(r'[?#&]gid=(\d+)', url)
    if not match or not gid:
        raise SystemExit('PAPERS_SHEET_URL must be the papers tab URL, with its gid')
    spreadsheet_id = match.group(1)
    values_api = build('sheets', 'v4', credentials=credentials, cache_discovery=False).spreadsheets()
    tabs = values_api.get(spreadsheetId=spreadsheet_id, fields='sheets.properties(sheetId,title)').execute()
    titles = [tab['properties']['title'] for tab in tabs['sheets'] if str(tab['properties']['sheetId']) == gid.group(1)]
    if len(titles) != 1:
        raise SystemExit(f'No tab with gid {gid.group(1)} in the Live Database')
    tab = "'" + titles[0].replace("'", "''") + "'"

    def read() -> list[list[str]]:
        return values_api.values().get(spreadsheetId=spreadsheet_id, range=tab).execute().get('values', [])

    def cell(grid: list[list[str]], row: int, column: int) -> str:
        return grid[row][column] if row < len(grid) and column < len(grid[row]) else ''

    grid = read()
    header = grid[0] if grid else []
    columns = {}
    for name in {'uid', *(change.column for change in changes)}:
        if header.count(name) != 1:
            raise SystemExit(f'Live Database {tab}: expected one "{name}" column, found {header.count(name)}')
        columns[name] = header.index(name)
    rows = {}
    for index, row in enumerate(grid[1:], start=1):
        uid = cell(grid, index, columns['uid']).strip()
        if uid in rows:
            raise SystemExit(f'Live Database {tab}: duplicate uid {uid}')
        rows[uid] = index

    planned, conflicts = [], []
    for change in changes:
        if change.uid not in rows:
            raise SystemExit(f'Live Database {tab}: no row for uid {change.uid}')
        row, column = rows[change.uid], columns[change.column]
        address = f'{column_letter(column)}{row + 1}'
        current = cell(grid, row, column)
        if current.strip() != change.before.strip():
            conflicts.append(f'  {address} paper {change.uid} {change.column}: sheet has {shown(current)}, '
                             f'expected {shown(change.before)}')
        planned.append((change, address, row, column))
    if conflicts:
        print('\n'.join(['Live Database changed since the last pull; nothing written:', *conflicts]))
        raise SystemExit('Run pull_from_google_sheet.py and rerun.')

    print(f'Live Database {tab}: {len(planned)} cells to update')
    for change, address, _, _ in planned:
        print(f'  {address:>6} paper {change.uid} {change.column}: {shown(change.before)} -> {shown(change.after)}')
    if input(f'Write these {len(planned)} cells to the Live Database? [y/N] ').strip().lower() != 'y':
        print('Live Database: not written.')
        return False
    values_api.values().batchUpdate(spreadsheetId=spreadsheet_id, body={
        'valueInputOption': 'RAW',
        'data': [{'range': f'{tab}!{address}', 'values': [[change.after]]} for change, address, _, _ in planned],
    }).execute()
    grid = read()
    wrong = [address for change, address, row, column in planned if cell(grid, row, column) != change.after]
    if wrong:
        raise SystemExit(f'Live Database: read-back differs at {", ".join(wrong)}')
    print(f'Live Database: wrote and verified {len(planned)} cells.')
    return True
