# 3-Hour Mock Conference Runbook

Goal: rehearse the full ISMIR virtual-conference pipeline end to end with **real Slack
and real Zoom** but **fake papers, PDFs, and videos**. Mock inputs live in
`sitedata_mock/` (generated, safe to delete and regenerate); the real 2025 data in
`sitedata/` is untouched.

## The real pipeline (what we are simulating)

Inputs, in the order they arrive during a real conference:

1. **Publication chairs** deliver the accepted-papers table (CSV/JSON export from the
   review system). It carries `uid`, `title`, authors + affiliations, abstract,
   subjects, and author emails.
2. **Program chairs** assign papers in the **`session_assignment` sheet matrix**;
   see [the assignment workflow](workflow.md#session-assignments).
3. **Authors** supply camera-ready PDF, poster PDF, slides, video (Google Drive
   links added as columns in the sheet).
4. Separate sheet tabs hold **events** (the program), **LBDs**, **music**, and
   **industry/sponsors**; a registration CSV feeds tutorial/sponsor invites.

Flow (each arrow is a script in this repo):

```
Google Sheet ──python pull_from_google_sheet.py──▶ sitedata/*.csv
sitedata/events.csv ──prepare-calendar──▶ ICS download
sitedata/*.csv ──miniconf_prep.py setup-*──▶ Slack channels ──▶ channel_url written back to CSV
sitedata/events.csv ──setup-zoom (utils/zoom.py)──▶ Zoom meetings ──▶ live/zoom links in CSV
sitedata/ ──main.py (Flask)──▶ site preview ──main.py --build──▶ static build ──▶ GitHub Pages
```

Outputs: the program website (one page per paper/LBD/performance/sponsor with
embedded PDF + video + "join Slack" button), a Slack workspace with one channel per
item (topic/purpose link back to the site page), Zoom meetings for live sessions,
and the schedule calendar.

See `SPREADSHEET_FORMAT.md` for the exact sheet tabs/columns and `workflow.md`
for the full per-file column reference.

## Mock inputs

`scripts/make_example_mock_data.py` (run from repo root, no credentials needed):

```bash
.venv/bin/python scripts/make_example_mock_data.py
```

Produces:

- `sitedata_mock/papers.csv` — 6 fake papers, all in session 1, day 1, with real-format
  Slack channel names (`p1-1-whale-song-structure`, …), placeholder author emails,
  and media pointing at local fakes.
- `sitedata_mock/events.csv` — the 3-hour program (times use the conference
  timezone configured in `sitedata_mock/config.yml` via
  `timezone: <IANA zone>`; for example `Asia/Dubai`, consumed by
  `scripts/calendar_csv2ics.py`, `main.py:localizetime`, and `utils/zoom.py`).
  Event Slack channel names are
  generated as sanitized title slugs such as `opening-session` or
  `poster-session-1`.

  | 18:00–18:10 | Opening | 19:45–20:10 | LBD Session |
  |---|---|---|---|
  | 18:10–18:30 | Mock Tutorial | 20:10–20:30 | Industry Session |
  | 18:30–19:00 | Oral Session 1 | 20:30–20:50 | Music Program |
  | 19:00–19:45 | Poster Session 1 | 20:50–21:00 | Closing & Awards |

  Days 2–5 get one filler event each because `main.py:group_by_days` hard-requires
  days 1–5.
- `mock_inputs/tutorial_registration.csv` — one fake registrant with the tutorial fee, for
  testing tutorial attendee assignment (`--registration-csv`). It deliberately lives outside
  `sitedata_mock/` so Flask does not publish attendee data as JSON.
- `sitedata_mock/lbds.csv` (2), `music.csv` (1, includes the `bb_id` column that
  `format_music` needs), `industry.csv` (2 sponsors).
- `sitedata_mock/config.yml` — copy of `sitedata/config.yml` renamed "ISMIR 2026 Mock Run",
  with `paper_day_release`/`lbd_day_release` set to 1 so everything is visible.
- `static/mock/*.pdf` — generated one-page placeholder PDFs (paper/poster/slides per
  paper, LBD abstracts, sponsor decks).
- Fake videos: every `video`/`youtube_id`/`yt_id` points at the CC-licensed
  Big Buck Bunny YouTube ID `aqz-KE-bpKQ`.
- `static/calendar/ISMIR_2026.ics` — built with
  the real `prepare-calendar` scripts (same ICS filename `main.py`'s `/getCalendar`
  download route serves).

## Mock Google Drive + master sheet

The 22 placeholder PDFs live in a real Drive folder:
<https://drive.google.com/drive/folders/1-0LdWqhrLIaJ9PsG7uhAN7As8LXAFPXk>
(file IDs in `scripts/mock_drive_ids.json`). Files carry `anyone: reader`
permission — embeds work without login (verified).

The same folder holds five **Google Sheets** named `papers`, `events`, `lbds`,
`music`, `industry` (IDs under `sheets` in `scripts/mock_drive_ids.json`),
pre-filled with the mock data and real Drive media links (`raw_* = open?id=...`). The real conference uses one sheet
with 5 tabs; the mock uses 5 single-tab sheets because they were created via
the Drive API, which can't add tabs — the CSV-export mechanism is identical.

**`uv run --env-file mockup.env python pull_from_google_sheet.py --mockup`** pulls the sheets named by the
`*_SHEET_URL` env vars in `mockup.env` (same names as `real.env`; tab URLs
with a `gid`) into `sitedata_mock/*.csv` via unauthenticated export URLs and rebuilds the calendar.
Verified end-to-end: edit sheet → `python pull_from_google_sheet.py --mockup`
→ `python main.py --mockup` → poster pages embed the Drive PDFs.

If you prefer the literal single-sheet setup, `scripts/make_sheet_export.py`
writes paste-ready **TSVs** to `sheet_export/` — paste each into a tab of one
sheet (cell A1; TSV splits into columns on paste, CSV does not) and use the
original `pull_from_google_sheet.py` with that sheet's ID + tab gids.

Videos stay YouTube (`aqz-KE-bpKQ`) — the video columns accept any iframe URL,
and LBD/music use YouTube IDs anyway.

## Rehearsal steps

### 1. Website (no credentials) — verified working

```bash
.venv/bin/python main.py --mockup
# → http://127.0.0.1:10000  (calendar, papers, poster_1..6, lbds, music_1, industry, day_1)
```

### Live Overview backend (real Zoom)

The rehearsal runs on its own backend: the same code as production, as a separate Worker and Durable
Object (`ismir-backend-mock`, `live_overview/wrangler.mock.jsonc`) at `live-api-mock.liweilin.org`, which
`sitedata_mock/config.yml` names as `live_overview_api`. Nothing done in a rehearsal reaches the production
schedule, Zoom grants or counts. The Warm-up Discussion keeps using its production backend.

One-time, from `live_overview/` (`secrets.mock.private.json` holds `ADMIN_KEY` and `TOKEN_ENCRYPTION_KEY`, as
generated by `scripts/init-secrets.mjs`; never reuse the production ones, and never commit them):

```bash
npx wrangler deploy -c wrangler.mock.jsonc
npx wrangler secret bulk secrets.mock.private.json -c wrangler.mock.jsonc
node scripts/smoke.mjs https://live-api-mock.liweilin.org https://daniel-chin.github.io
```

1. In the mockup repository, set the `LIVE_OVERVIEW_ADMIN_KEY` Actions secret to the mock `ADMIN_KEY`. Its
   build then pushes the mock schedule to this backend, despite the warnings a small program always raises;
   `build_miniconf.py` refuses to push mock data to the production backend.
2. Create a separate Zoom App from `live_overview/observer_config/ISMIR2026 Mock Observer v1.json`. Don't
   repoint a production app: it would cut off the production Observers.
3. On `https://live-api-mock.liweilin.org/admin.html`, configure the app as `v1` with origin
   `https://live-api-mock.liweilin.org` and its Client ID, Client Secret and Webhook Secret Token.
4. Install it from `https://live-api-mock.liweilin.org/zoom/oauth/start/v1`, then open it inside a Zoom meeting:
   the host chooses Central attendance, co-hosts in rooms choose Room speakers.
5. The mock events' Zoom links come from `setup-zoom` below, like production's.

### 2. Slack (real workspace, needs setup)

Full Slack reference in [SLACK.md](SLACK.md).

One-time: create a free test Slack workspace, create a Slack app with bot scopes
`channels:manage`, `channels:read`, `groups:write`, `chat:write`, `users:read`,
`users:read.email`, install it, and put in `mockup.env` (gitignored):

```
SLACK_BOT_TOKEN=xoxb-...
SLACK_USER_TOKEN=xoxp-...
SLACK_TOKEN_ANNOUNCEMENT_BOT=xoxb-...
DUMMY_EMAIL=<your-email-in-that-workspace>   # invites go here in non-prod mode
```

Create and populate the paper channels:

```bash
python miniconf_prep.py --mockup --action setup-papers-create-channels
python miniconf_prep.py --mockup --action invite-authors-to-channels      # non-prod → invites DUMMY_EMAIL
python miniconf_prep.py --mockup --action setup-papers-set-desc
python miniconf_prep.py --mockup --action set-event-channel-desc
```

Tutorial channels created by `create-tutorial-channels` are private in the
mock workspace as well.

### Tutorial invitation workflow

### Channel writeback

`create-channels` writes `channel_url` back into the CSV → restart `main.py` and the
poster pages grow a working "Slack" button. `set-event-channel-desc` sets each 
channel purpose to that session's Zoom URL, and
`setup-papers-set-desc` sets each paper channel purpose to include a
within-Slack link to the matching poster-session channel. The paper purpose also
includes the program-site link; the base URL is `miniconf_url` from config.yml.

LBD/music/tutorial/sponsor channel setup (`setup-lbd`, `setup-music`, …) uses
the same pipeline but is less exercised than the papers path; papers are the
representative test.

### 3. Zoom (real account, needs setup)

Full reference: [ZOOM.md](ZOOM.md) (app creation, scopes, API surface, troubleshooting).

Create a Zoom Server-to-Server OAuth app, add to `.env`:

```
ZOOM_API_ACCOUNT_ID=...
ZOOM_API_CLIENT_ID=...
ZOOM_API_CLIENT_SECRET=...
```

The `setup-zoom` action is fully wired:

```bash
.venv/bin/python miniconf_prep.py --mockup  --action setup-zoom             # dry-run, no API calls
.venv/bin/python miniconf_prep.py --mockup  --action setup-zoom --prod true # creates meetings
```

`ZoomCreator` skips the `Tutorials`/`Lunch`/`Social` categories (the mock buffer
days are `Social`, so the 3-hour program yields 7 meetings). Events titled
`Poster Session - N` additionally get one pre-created **breakout room per poster**
(Zoom matches `day` + `session` from session assignment, rooms named after the
paper's Slack channel, e.g. `p1-1-whale-song-structure`) — after the poster
craze the host opens the rooms and each poster gets its own. Rooms are patched
onto the meeting even when the link is only backfilled, so meetings created
before a papers-sheet update pick up the rooms on re-run. Zoom caps pre-created
rooms at 50/meeting and names at 32 chars. `ZoomCreator` calls
`utils/zoom.py:createZoomLinksIfNeeded`, which creates one meeting per remaining
row and writes the `join_url` into `live_url` in `events.csv`. It is idempotent
by meeting topic: rows whose title already has a Zoom meeting get the existing
URL backfilled instead of a duplicate — so when `python pull_from_google_sheet.py --mockup` re-pulls the
sheet and wipes `live_url`, re-running `setup-zoom` restores the links (copy them
back into the events sheet if the sheet should stay authoritative). Meeting start
times are interpreted in the timezone configured in
`sitedata_mock/config.yml` and durations come from `start_time`/`end_time`.
Breakout rooms are
verified by reading the meeting back after create/patch — if the account's
breakout-room setting is off, the run fails loudly instead of silently creating
room-less meetings. Caveat: free Zoom accounts cap meetings at 40 min.

### 4. Run the 3 hours

- T-0:15 — start site (or run the `Refresh website` workflow in the mockup repo), post welcome in Slack `#general`.
- 18:10 — run the mock tutorial and verify its page and private Slack channel.
- 18:30 — open the Oral Session Zoom from the calendar's `live_url`.
- 19:00 — poster session: Q&A happens in the per-paper channels (`p1-1-…` … `p1-6-…`).
- 20:10/20:30 — sponsor + music pages with embedded fake PDF/video.
- Debrief: check `channel_url` round-trip, calendar links, timezone rendering.

## What still needs a human

| Item | Why |
|---|---|
| Slack workspace + bot token in `.env` | credentials |
| Zoom S2S OAuth creds in `.env` | credentials |
| Real author emails + `--prod` flag | only for the real event, never for tests |
| Sponsor registration CSV (`setup-sponsors`) | not part of the 3-hour mock; a fake tutorial registration is included |
