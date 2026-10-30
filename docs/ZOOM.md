# Zoom integration

Creates Zoom links for live sessions in the events CSV, writes the join URLs
back into the CSV's `live_url` column (which the site and calendar link to).
Uses one Zoom meeting per poster session with breakout rooms, and uses one
shared Zoom webinar link for all non-poster live events.

## Architecture

```
sitedata/events.csv ─┐
                     ├─ miniconf_prep.py --action setup-zoom
sitedata/papers.csv ─┘        │
                              ▼
                   modules/zoom_creator.py (ZoomCreator)
                     · filters events that need a Zoom link
                     · maps non-poster events → shared webinar join URL
                     · maps "Poster Session - N" → its papers → breakout room names
                              │
                              ▼
                   utils/zoom.py (Zoom REST API, S2S OAuth)
                     · meeting/webinar creation and backfill → live_url written into events.csv
```

| File | Role |
|---|---|
| `utils/zoom.py` | Thin Zoom REST API client: OAuth token handling plus meeting/webinar CRUD helpers used by `setup-zoom` |
| `modules/zoom_creator.py` | `ZoomCreator`: decides which events get poster-session meetings and which reuse the shared webinar |
| `miniconf_prep.py` | CLI entry point (`--action setup-zoom`) |

## One-time setup (human, ~5 min)

Zoom app creation is browser-only; there is no API for it. The person must be
an **owner/admin** of the Zoom account.

1. Sign in at <https://marketplace.zoom.us>.
2. **Develop → Build App → Server-to-Server OAuth**, name it (e.g. `ismir2026`).
3. The **App Credentials** page shows the three values you need.
4. **Scopes** tab, add:
   - Meeting scopes for poster sessions: `meeting:write:meeting:admin`; `meeting:read:list_meetings:admin`; `meeting:read:meeting:admin`; `meeting:update:meeting:admin`
     (granular scopes on S2S apps carry the `:admin` suffix; older accounts
     show classic `meeting:write` / `meeting:read` instead)
   - Webinar scopes for the shared livestream webinar used by all non-poster events: `webinar:write:webinar:admin`; `webinar:write:invite_links:admin`; `webinar:update:webinar:admin`; `webinar:read:list_webinars:admin`; `webinar:read:webinar:admin`.
5. **Activate** the app — credentials don't work until activated.
6. In the repo root, create `.env` (already gitignored — never commit it):

   ```
   accountId=...
   clientId=...
   clientSecret=...
   ```

7. Smoke test (read-only, creates nothing):

   ```bash
  .venv/bin/python -c "from utils import zoom; print(zoom.getListOfMeetings()); print(zoom.getListOfWebinars())"
   ```

1. Account settings: 

Open the Zoom web portal and go to [Settings → Meeting](https://us04web.zoom.us/profile/setting#tab-meeting)  
→ Security:  
  - Disable "Only authenticated meeting participants and webinar attendees can join meetings and webinars"
  - Disable "Only authenticated users can join meetings from Web client"
→ In Meeting (Advanced):
  - Enable **Breakout room**. Under it,
  - Enable "Set default breakout room behaviors". In "Edit Options", 
  - Enable "Allow participants to choose room", "Allow transcript in breakout rooms", and click "Continue".
  - Enable "Manual captions", if you have live captioning provider.

if anything is wrong, the Zoom API silently
drops the room definitions. `utils/zoom.py` guards against this: after every
create/patch that includes rooms it reads the meeting back and raises
`Breakout rooms did not persist ...` if Zoom kept none (or the wrong set) —
so a misconfigured account fails loudly on the first poster session instead
of being discovered on conference day.

ISMIR2026 chose to purchase its own Zoom licenses:  
- Zoom Workplace Pro x 1 from Aug to Nov.  
- 300-attendee Webinars x 1 for Sep.  
- 500-attendee Webinars x 1 for Nov.  

### Shared webinar to be scheduled by script

`setup-zoom` must create or backfill one webinar for all non-poster live
events. When constructing the webinar API call, use the following target
settings:

- Topic: `ISMIR2026 Livestream`
- When/Duration: 0600 - 2359
- Recurring: every day, for the duration of the conference
- Registration and authentication: not required for anyone
- Security/features: use passcode; enable Q&A, practice session, HD video,
  and record in cloud

## Running it

```bash
# dry-run: prints what would be created, no API calls
.venv/bin/python miniconf_prep.py --mockup --action setup-zoom

# real run: creates poster-session meetings and the shared webinar, then writes
# live_url back into events.csv
.venv/bin/python miniconf_prep.py --mockup --action setup-zoom --prod true
```

Omit `--mockup` for the real conference data. `setup-zoom` needs only the
Zoom credentials — no `SLACK_BOT_TOKEN` (module imports in `miniconf_prep.py` are
deferred per action for exactly this reason).

Set the same passcode for all poster-session meetings and for the shared
webinar.

## Static Zoom redirect utility

The website does not expose `live_url` directly in UI links. Instead it routes via
the static utility page:

- Website links: `zoom.html?event_uid=<event_uid>`
- Slack-originated links: `zoom.html?event_uid=<event_uid>&token=<conference_token>`

### Config

Set a conference-wide token in `.env`, whose value can be arbitrary:

```
ZOOM_REDIRECT_ACCESS_TOKEN=<token>
```

### Inputs

- `event_uid`: event `uid` from `events.csv`
- `token`: conference token (typically included in Slack-originated links)

The utility resolves the target event from `events.csv` and uses that event's
`live_url` as the full Zoom join URL.

### Redirect behavior

- If a valid current token (`token` URL param) or valid saved token exists:
  redirect to full `join_url` (includes `pwd` when present).
- If token is missing/invalid: the page shows that one-time access is still
  available with manual passcode entry, and persistent access can be enabled by
  joining from Slack.
- In the missing/invalid-token case, `Join Zoom now` redirects to the same Zoom
  join URL with `pwd` removed.

### User state on `zoom.html`

- `INITIAL`: checkbox is checked by default; nothing is saved; no auto-redirect.
- `YES`: save credential locally; show 3-second countdown; auto-redirect.
- `NO`: remove saved credential; show 3-second countdown; auto-redirect without
  using saved credential.

`Join Zoom now` always redirects immediately and updates state based on the
checkbox.

### What it does

For every row in `events.csv`, `setup-zoom` splits behavior into three paths:

1. Poster sessions keep the existing meeting flow described below.
2. Every non-poster live event shares the same webinar join URL.
3. Tutorials remain manually created, and `Lunch` / `Social` need no call.

For non-poster live events:

1. Pull existing webinar of the same name from account, if any.
2. Create / update the webinar with [above settings](#shared-webinar-to-be-scheduled-by-script).
3. For each live event, write its `join_url` into that
  row's `live_url`.

The CSV is rewritten in place; a summary line should report created vs
backfilled links.

### Poster sessions → breakout rooms

The real-conference format: all posters get a short "poster craze" pitch in the
main room, then everyone splits into one breakout room per poster.

Events titled `Poster Session - N` get one pre-created breakout room per paper:
Papers are matched on `day` == event's `day` and `session` == `N` from
`session_assignment.csv`, ordered by their position in the matrix, and each room is named after the paper's
Slack channel (e.g. `p1-1-whale-song-structure`) so the same handle identifies
the poster on the site, in Slack, and in Zoom.

If the poster meeting already exists (backfill path), the rooms are **patched
onto it** via the meeting-update API, so meetings created before a papers-sheet
update pick up rooms on the next run.

During the session the host still clicks **Open all rooms** after the craze.
"Let participants choose room" is enabled by the host in the breakout dialog
(client ≥ 5.3) — it is not settable via the API.

## Idempotence and the sheet round-trip

Meetings and the webinar are keyed by **topic == event title** (with a `mock-`
prefix under `--mockup`, so mock and real entries never match). Re-running
`setup-zoom` should never duplicate a meeting.

If `python pull_from_google_sheet.py` / `python pull_from_google_sheet.py --mockup` ever overwrite `events.csv` — including `live_url`, simply re-run `setup-zoom`: existing poster meetings are found by title, the shared webinar is found by its fixed identity, and URLs are backfilled.

Corollary: event titles are identity keys for those
meetings. Renaming an event in the sheet and re-running creates a second
meeting; manually delete the old (zombie) one.

## utils/zoom.py technicality

Credentials are loaded lazily from `.env` on the first API call (importing the
module never requires them; a missing credential raises a `RuntimeError` naming
the variable). The OAuth token is cached module-globally and refreshed ~10 s
before expiry.


## Zoom platform constraints

- **Free accounts cap meetings at 40 min.** ISMIR2026 chose the paid plan.
- Pre-created breakout rooms: max **50 rooms** per meeting, room names max
  **32 chars** (the code truncates both).
- One host can run only one meeting at a time on a basic account; back-to-back
  scheduled meetings are fine, overlapping live ones are not.
- Meeting list pagination uses `next_page_token` with `page_size=300`.
- Meeting creation is rate-limited to **100 requests per user per day** — fine
  for poster sessions, but a mass delete-and-recreate could hit it.
- Webinar licensing, attendee capacity, recurrence, and webinar-specific
  feature limits exist.

## Testing without credentials

`scripts`-free offline check: monkeypatch the API layer and run the real
orchestration logic against a copy of the mock CSV —

```python
from utils import zoom
zoom.getListOfMeetings = lambda: []
zoom.getListOfWebinars = lambda: []
zoom.createMeeting = lambda topic, start, dur, rooms=None: {
    "id": 1, "topic": topic, "join_url": "https://zoom.us/j/1"}
zoom.createWebinar = lambda *args, **kwargs: {
  "id": 2, "topic": "ISMIR2026 Livestream", "join_url": "https://zoom.us/w/2"}
zoom.updateMeetingBreakoutRooms = lambda mid, rooms: 204

from modules.zoom_creator import ZoomCreator
ZoomCreator("events_copy.csv", useDummyValues=False,
            papersCsvFile="sitedata_mock/papers.csv").setupZoomCalls(zoom)
```

This exercises poster-session filtering, breakout-room mapping, idempotence,
and the backfill-after-wipe path end to end (see MOCKUP.md § 3 for the mock
context). Add a corresponding webinar mock when testing the shared non-poster
livestream path offline.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `RuntimeError: Missing Zoom credential ...` | `.env` absent or incomplete in the repo root (it's read relative to the CWD — run from repo root) |
| `Zoom OAuth token request failed: {'reason': 'Invalid client_id or client_secret'...}` | wrong creds, or app not **activated** |
| `... failed: {'code': 4711, ...}` / scope error | missing `meeting:write` scope on the app |
| `RuntimeError: Breakout rooms did not persist on meeting ...` | breakout rooms disabled in the account's meeting settings — Zoom accepted the request but silently dropped the rooms (the read-back check caught it) |
| Duplicate meetings after a sheet edit | event title changed — titles are the identity key (see above) |
| `live_url` empty after the data pull | expected — re-run `setup-zoom` to backfill |
