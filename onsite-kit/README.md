# Onsite kit

A local web page for the onsite MacBooks: conference links, poster-session links, the LBD video
screens, and the LBD and MIREX materials. It runs on Python 3.9+ with no packages. Use Chrome: the player shows posters in its PDF viewer.

| Page | For |
|---|---|
| **Links** | Miniconf, Zoom, Slack, YouTube, Live Database and operations links |
| **Poster sessions** | Zoom, Slack and miniconf links of all 14 sessions; the live and next ones are marked |
| **Talk sessions** | The 14 oral and 3 award sessions; in each, its papers in order with buttons to open the slides or paper, or show them in Finder |
| **LBD screens** | The 7 video screens: Play and Manage for each |
| **LBD posters** | The 4 poster screens: Play and Manage for each |
| **Materials** | Every LBD and MIREX file on Drive against this MacBook: choose what to download or update |
| **Paper materials** | The same for the papers and slides of the oral and award sessions |

## Before the conference

`.onsite_env` holds links only: to the Drive folders and to the Live Database tabs. Each MacBook reads the tabs
itself (see [The Live Database](#the-live-database)), so a change in the sheets, or a new column, needs no new
`.onsite_env`; only a new or moved tab or folder does.

**Once, on an organizer's machine** (needs the env files of `pull_from_google_sheet.py`):

```bash
uv run --env-file low_keys/real.env --env-file high_keys/real.env python onsite-kit/make_env.py
```

The first time, copy `onsite_env.example` to `.onsite_env` and fill in `DRIVE_FOLDER_LBD` and
`DRIVE_FOLDER_MIREX` (the camera-ready folders), `DRIVE_FOLDER_CHANNELS` (the Slack channel QR codes),
`DRIVE_FOLDER_SUBTITLES` (see [Subtitles](#subtitles)), and `SHEET_ORAL_SESSIONS` and `SHEET_AWARD_SESSIONS`
(those tabs of the Live Database). `make_env.py` adds the links of the other tabs (`SHEET_PAPERS`,
`SHEET_EVENTS`, `SHEET_SESSION_ASSIGNMENT`, `SHEET_LBDS`, `SHEET_LBD_GROUPS`) and keeps the lines you wrote.
To add rows to the links table, see the example file.

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

## The Live Database

Everything the pages show but the media comes from the Live Database, read on this MacBook (`livedb.py`): the
links, the poster sessions and the LBD slot (Events), the LBDs and MIREX entries (LBDs, with all of MIREX), the
groups (LBD groups), and the oral and award sessions (their tabs, Papers and Events). The website's
`sitedata/config.yml` (in the repo) adds the time zone and the conference's own links. The tabs need only be
shared with anyone with the link, so no login is needed.

The tabs are read when the server starts, from the **Live Database** button at the top right of every page,
and before each *Check Drive for updates*. The button shows when they were last read, in red if that failed.
The last reading stays in `.state/live.json`, so the kit works without a network, as it last was.

## Materials

Files go to `media/{papers,posters,videos,thumbnails,captions,channels,subtitles}/<uid>.<ext>` (the talks' to
`media/talks/`, see [Talk sessions](#talk-sessions)); the groups' channel
codes are the rows `g1` to `g7`.

*Check Drive for updates* takes about 2 minutes and compares each file's size with Drive's. It runs by
itself the first time. The result stays, so the page works offline.

Tick single files, a row, or a whole column (click its title), or use *Select everything to update*; ticking
*Only what needs updating* lists those files and selects them all, Slack channel codes included. Any file
can be ticked to download it again, and filters narrow the list by search, screen or status. Downloads
can be cancelled, and pick up where they stopped, even after a restart. A new file replaces the old one only
once it is complete, so a running player is safe; open Manage afterwards if a video changed.

If Drive refuses with a quota error, try later or copy `onsite-kit/media/` from another MacBook. Copied files
count as up to date.

## Talk sessions

From the oral and award session tabs, Papers and Events (see [The Live Database](#the-live-database)) come the
sessions (time and room from Events; chairs; papers in order, with presenter and onsite or remote) and each
paper's links: its PDF (Papers), and its slides as PDF for each session (`slides_pdf`; the preferred format is
not used).

**Paper materials** works like Materials, against those links: *Check Drive for updates*, then download.
Files go to `media/talks/{papers,slides_pdf,award_slides_pdf}/<uid>.<ext>`. A Google Slides link downloads as
PowerPoint; Google tells its size only by sending it, so it shows `?` once downloaded: tick it to fetch it
again. A link not shared with anyone with the link fails the check, and is listed.

**Talk sessions** lists the sessions, the live and next ones marked. In a session, each paper has *Open slides*
(this session's slides, in their own app), *Paper PDF*, and *Show in Finder*. Slides on a web page open in the
browser, and a note in the sheet in place of slides shows under the presenter. The page shows newly downloaded
files within 30 seconds.

## LBD screens

Each screen plays its videos back to back, each after a cover with its code, title, authors,
affiliations and the QR codes of its paper and group Slack channels, and a faint ring in its top right
corner that fills as the cover's time runs out; there are no posters. Each video fades out over its last second, and the cover fades
in over it and out over the next video. A bar on top shows the code and how far the video has played, and
scrolls the titles of this video and the next. Before the start, the screen shows its timetable.

As planned from the Live Database on 7 November:

| Screen | Topic | Videos | Plays | Cover | Total |
|---|---|---:|---:|---:|---:|
| 1 | Music Generation | 15 | 30 | 15 s | 119.8 min |
| 2 | Performance Analysis | 16 | 30 | 13 s | 119.8 min |
| 3 | Symbolic / Notation | 13 | 26 | 20 s | 115.7 min |
| 4 | Representations / Retrieval | 13 | 26 | 20 s | 114.4 min |
| 5 | Audio Synthesis / Production | 12 | 24 | 20 s | 113.7 min |
| 6 | Human-Centered MIR (+626, +689 once each) | 13 | 24 | 20 s | 110.1 min |
| 7 | MIREX | 10 | 30 | 20 s | 119.1 min |

### LBD plan

The screens show the LBDs presented online and cleared to present: `presentation_mode` Virtual and
`ok_to_present` not No in the LBDs tab. In-person ones present at their poster. The MIREX overview, m1, is the
exception: it plays on the video screen whatever the sheet says, and has no poster. Each LBD plays on the
screen of its group (`group_id`), twice, MIREX three times: once through in uid order, then again. Where a
screen cannot hold them all with covers of 10 s, the extra plays move to the end of the screen with the most
time to spare, first those of LBDs new to that screen, then those of the longest videos. The cover takes what
the slot leaves, up to 20 s.

Each MacBook works this plan out from the Live Database (`lbdplan.py`), with the lengths its video files
state, so every MacBook comes to the same plan without copying anything. When a reading of the Live Database
changes it, the LBD screens and LBD posters pages say how, with **Update the screens**: do that on every
MacBook. A screen playing at the time jumps to the new plan; a changed screen loses its edits in Manage, but
keeps its start time. The plan in use is kept in `.state/lbd_plan.json`.

`lbd_schedule.json` in the repo is the reference: the plan a new MacBook starts with, the screens' names, the
YouTube lengths of videos not downloaded, and what counts as new to a screen. `python3 onsite-kit/plan_lbd.py`
writes the current plan into it, on a machine with the videos; commit the result.

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

## Subtitles

The video screens show subtitles under videos that have none in the picture. Chrome cannot show the
authors' caption files or the subtitle tracks inside the videos, so an organizer turns them into one
`<uid>.vtt` per video, once, and shares them through Drive like every other file:

1. **On an organizer's machine** with every video and caption file downloaded, ffmpeg, and YouTube's
   automatic captions in `local/youtube_captions/` (`<uid>.en-orig.vtt`, from yt-dlp):
   `python3 onsite-kit/build_subtitles.py`. It writes `local/subtitles/<uid>.vtt`, taking for each video the
   authors' caption file, else the video's own track, else YouTube's captions. Videos with subtitles in the
   picture (listed in the script) get no file.
2. Upload those files to the Drive folder of `DRIVE_FOLDER_SUBTITLES`, shared by link, replacing old ones.
3. **On each MacBook**: *Check Drive for updates*, then download the Subtitles column. New or changed
   files show as ↓ or ↻ like any other. A player picks a file up at the start of the video's next play.

A video with no file plays without subtitles, as before.

## LBD posters

The 4 poster screens show the posters of the LBDs on the video screens (see [LBD plan](#lbd-plan)), but not
the MIREX overview, in group order, split into 4 runs of 23, 23, 23 and 20 posters: 5:13 each, from 15:00 to
17:00. Within each run the posters are ordered so that none is up while its own video or cover is on a video
screen, with 30 s to spare. This is part of the LBD plan, worked out with the video screens' plan. The LBD
screens, LBD posters and Manage pages warn of any clash that edits on the day make; *Reset to default plan*
brings a poster screen back to the plan.

Posters are drawn whole, scaled to the screen, by pdf.js (`web/vendor/pdfjs`), not shown in Chrome's PDF
viewer. A landscape poster fills the screen's height, and a column on its right takes the width it leaves
(15-27% of the screen; an upright poster gets an A0 poster's column): the poster's code and time, the QR codes
of its paper and group Slack channels, and the next poster; the next poster loads in the background and fades in. Before the start the screen
lists its posters by group, with a countdown. Each screen has a Manage page like the video screens: start time,
order, adding or removing posters, and the time per poster.

## Files

| File | Role |
|---|---|
| `make_env.py` | Puts the links of the Live Database tabs into `.onsite_env` |
| `serve.py` | The local server, and the store of each screen's schedule |
| `materials.py` | Compares Drive with `media/` and downloads files |
| `lbd_schedule.json` | The reference LBD plan: what a new MacBook starts with |
| `lbdplan.py` | Works out the LBD plan, video and poster screens, from the Live Database |
| `plan_lbd.py` | Writes the current LBD plan into `lbd_schedule.json` |
| `livedb.py` | Reads the Live Database on each MacBook: links, sessions, LBDs and groups, the paper schedule |
| `build_subtitles.py` | Makes the subtitle files for the Drive folder, on an organizer's machine |
| `web/` | The pages; `lbd-timeline.js` holds the timing logic, `vendor/pdfjs/` draws the posters |
| `.onsite_env`, `media/`, `.state/` | Private or local: gitignored |

Tests: `node --test onsite-kit/test_timeline.cjs` and `pytest tests/test_onsite_kit.py`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Empty links or sessions | `.onsite_env` is missing or misplaced (restart `serve.py` after changing it), or the Live Database was never read: click the button at the top right, online |
| Live Database button red | A tab could not be read (offline, or not shared by link): the pages show the last reading; hover for the error |
| "Address already in use" | `serve.py` is already running, or use `--port 8766` |
| `python3` opens an installer | Accept it: the Command Line Tools include both git and Python |
| Red "video will not play" | Replace the file with an H.264 mp4 as `media/videos/<uid>.mp4`; open Manage again |
| Materials warns of unknown Drive folders | A folder whose uid, or whose files, the LBDs tab does not list: add the LBD to the sheet, then *Check Drive for updates* again |
| Screen out of step | Check the MacBook's clock, then reload the player |
| Screen sleeps | Start `serve.py` with `caffeinate -d` |
