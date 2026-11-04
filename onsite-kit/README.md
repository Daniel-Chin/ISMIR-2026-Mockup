# Onsite kit

A local web page for the onsite MacBooks: conference links, poster-session links, the LBD video
screens, and the LBD and MIREX materials. It runs on Python 3.9+ with no packages. Use Chrome: the player shows posters in its PDF viewer.

| Page | For |
|---|---|
| **Links** | Miniconf, Zoom, Slack, YouTube, Live Database and operations links |
| **Poster sessions** | Zoom, Slack and miniconf links of all 14 sessions; the live and next ones are marked |
| **LBD screens** | The 7 video screens: Play and Manage for each |
| **Materials** | Every LBD and MIREX file on Drive against this MacBook: choose what to download or update |

The 4 LBD poster monitors are not covered yet.

## Before the conference

**Once, on an organizer's machine** (needs `.env`, `sitedata/` and `local/mirex/`):

```bash
uv run --env-file low_keys/real.env --env-file high_keys/real.env python pull_from_google_sheet.py
uv run python onsite-kit/make_env.py
```

The first time, copy `onsite_env.example` to `.onsite_env` and fill in `DRIVE_FOLDER_LBD` and
`DRIVE_FOLDER_MIREX` (the camera-ready folders) and `DRIVE_FOLDER_CHANNELS` (the Slack channel QR codes). `make_env.py` generates the rest.
Rerun it after any change in the sheets: it keeps the lines you wrote. To add rows to the links table,
see the example file.

**On each MacBook** (`.onsite_env` is gitignored, and this repo is public, so copy it privately):

```bash
git clone https://github.com/Daniel-Chin/ISMIR2026-Kit.git
cp <from your private copy>/.onsite_env ISMIR2026-Kit/onsite-kit/
```

Then start the kit and download everything: **Materials → Select everything to update → Download selected**.
That is 545 files, 6.1 GB.

## Every day

```bash
cd ISMIR2026-Kit
caffeinate -d python3 onsite-kit/serve.py      # keeps the MacBook awake
```

Open <http://127.0.0.1:8765>. The server only answers on this MacBook.

## Materials

Files go to `media/{papers,posters,videos,thumbnails,captions,channels}/<uid>.<ext>`; the groups' channel
codes are the rows `g1` to `g7`.

*Check Drive for updates* takes about 2 minutes and compares each file's size with Drive's. It runs by
itself the first time. The result stays, so the page works offline.

Tick single files, a row, or a whole column (click its title), or use *Select everything to update*. Any file
can be ticked to download it again, and filters narrow the list by search, screen or status. Downloads
can be cancelled, and pick up where they stopped, even after a restart. A new file replaces the old one only
once it is complete, so a running player is safe; open Manage afterwards if a video changed.

If Drive refuses with a quota error, try later or copy `onsite-kit/media/` from another MacBook. Copied files
count as up to date.

## LBD screens

Each screen plays its videos back to back, each after a cover with its code, title, authors,
affiliations and the QR codes of its paper and group Slack channels; there are no posters. Each video fades out over its last second, and the cover fades
in over it and out over the next video. A bar on top shows the code and how far the video has played, and
scrolls the titles of this video and the next. Before the start, the screen shows its timetable.

| Screen | Topic | Videos | Plays | Cover | Total |
|---|---|---:|---:|---:|---:|
| 1 | Music Generation (+666, +682) | 15 | 30 | 15 s | 119.9 min |
| 2 | Performance Analysis (+669) | 14 | 28 | 20 s | 114.3 min |
| 3 | Symbolic / Notation (+610) | 13 | 26 | 20 s | 115.7 min |
| 4 | Representations / Retrieval (−666) | 13 | 26 | 20 s | 114.5 min |
| 5 | Audio Synthesis / Production (−610, −682) | 12 | 24 | 20 s | 113.7 min |
| 6 | Human-Centered MIR (−669) | 13 | 26 | 20 s | 117.5 min |
| 7 | MIREX | 11 | 33 | 6 s | 119.9 min |

The cover takes what the slot leaves, up to 20 s.

Only virtual LBDs play: in-person ones present at their poster; the MIREX overview, m1, plays too. Each
video plays twice, MIREX three times: once through in uid order, then again. The default plans are
in `lbd_schedule.json`, with the YouTube lengths. These lengths are replaced by the real ones when you
open a screen's Manage page.

**Setup.** After downloading, open Manage once for your screen. It measures the videos, and marks files that
are missing or that Chrome cannot play. Then open Play, drag the window to the monitor and press `F`.

**Player.** It works out what to show from the clock alone, so it can be opened or reloaded at any time and
joins at the right second. By default every screen starts at the scheduled 15:00. Before that it shows
a countdown. All times are venue time, whatever the MacBook's time zone is, so check that its clock is
set automatically. `F` fullscreen; `M` sound, off by default. A missing video leaves the poster up
for that time, so the screens stay in step.

**Manage.** Each MacBook keeps its own schedules in `.state/`, and an open player follows changes within
3 seconds.

- *Set start*, *Play from the beginning now*, *Back to the scheduled start*.
- Reorder (*Next*, ↑ ↓), remove, or add any LBD. Plays already shown and the one on screen are locked;
  edits never make the player jump.
- *Fit posters to the slot* picks the poster time that makes the remaining plays end by the end of the slot.
- *Reset to default plan* discards this screen's changes.

## Files

| File | Role |
|---|---|
| `make_env.py` | Fills `.onsite_env` from the private data |
| `serve.py` | The local server, and the store of each screen's schedule |
| `materials.py` | Compares Drive with `media/` and downloads files |
| `lbd_schedule.json` | Default plan per screen |
| `web/` | The pages; `lbd-timeline.js` holds the timing logic |
| `.onsite_env`, `media/`, `.state/` | Private or local: gitignored |

Tests: `node --test onsite-kit/test_timeline.cjs` and `pytest tests/test_onsite_kit.py`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Empty links or sessions | `.onsite_env` is missing or misplaced; restart `serve.py` after changing it |
| "Address already in use" | `serve.py` is already running, or use `--port 8766` |
| `python3` opens an installer | Accept it: the Command Line Tools include both git and Python |
| Red "video will not play" | Replace the file with an H.264 mp4 as `media/videos/<uid>.mp4`; open Manage again |
| Materials warns of unknown Drive folders | A new LBD: pull the sheets, rerun `make_env.py`, copy `.onsite_env` to the MacBooks |
| Screen out of step | Check the MacBook's clock, then reload the player |
| Screen sleeps | Start `serve.py` with `caffeinate -d` |
