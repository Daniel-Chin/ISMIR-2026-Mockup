# Repeatable jobs
## Job: Digest new uploads of presentation materials.
Nothing is pasted by hand. Every step that changes the Live Database or YouTube prints its changes
first and writes only after you answer `y`.

One-time setup:
- `.env`:
  - `PAPERS_SHEET_URL`: the papers tab URL, with its `gid`.
  - `SESSION_ASSIGNMENT_SHEET_URL`: the session matrix ("Session to Papers" tab of the schedule sheet), not the
    pointer tab in the Live Database. YouTube titles (`P{session}-{position} …`) come from it.
  - `google_client_id`, `google_client_secret`: the OAuth client.
- In that OAuth client's Google Cloud project, enable the Google Drive API, the Google Sheets API and the
  YouTube Data API.
- Share the Live Database with zoom.admin.ismir2026@gmail.com as an editor.
- `ffmpeg` and `ffprobe` are installed (WSL: `sudo apt install ffmpeg`).
- Each script that calls Google prints a login URL: open it in a browser and log in as
  zoom.admin.ismir2026@gmail.com.

Steps:
- cd to ismir2026-kit
- `git pull`
- Go to "Upload your presentation materials for ISMIR2026"
- Download csv to any `$csv_path` (e.g. `local/`, which git ignores)
- `uv run python pull_from_google_sheet.py`
  - Always, right before parsing: the parser tells a manual edit from an earlier submission by comparing with
    `sitedata/papers.csv`.
- `uv run python -m scripts.parse_google_form_author_uploaded_materials --input $csv_path`
  - It updates `sitedata/papers.csv` and lists the changed cells per column, then the papers with new videos
    or captions, as a ready `--uids` command.
  - "keeping manual value" lines: a cell that matches no submission is kept. Check that it really was edited
    by hand.
  - After the login, it lists every cell it will write to the Live Database papers tab, before -> after.
    Answer `y` to write them. It writes only those cells, reads them back, and stops without writing if any
    of them changed since the pull.
- If it listed no new videos or captions, EXIT this process!
- `uv run python -m scripts.download_and_rename_videos_and_captions --uids <the uids it listed>`
  - Downloads through the Drive API into `tmp/videos` and `tmp/captions`. "failed >0": check those files.
- `uv run python -m scripts.police_videos`
- Is any video longer than 3:10? Notify authors.
- `uv run python -m scripts.time_stretch_videos`, or leave such a video out of the upload until the authors
  send a shorter one. It retimes the video's captions by the same speed.
- Upload the new videos in YouTube Studio (zoom.admin.ismir2026@gmail.com): select the files in `tmp/videos`.
  - Keep the title as the file name (the paper uid, e.g. `13`) and leave the description empty: that is how
    the next step recognises a fresh upload and its paper.
  - Not made for kids; visibility Unlisted; Save. A dialog closed early leaves a Draft.
  - `decorate_youtube_videos --upload <uids>` can upload them instead, but each upload costs a large part of
    the daily API quota.
- `uv run python -m scripts.decorate_youtube_videos`
  - Upload first, then run it once: it marks a paper's old video `[outdated]` and private as soon as the paper
    has a new `raw_video`, so running it before the upload leaves the paper without a video meanwhile.
  - It lists every planned YouTube change (titles, descriptions, captions, outdated videos, playlists) and
    asks before applying them. Then it lists the new `video` links and asks before writing them to the Live
    Database.
  - At the end it lists the papers still without a current YouTube video.
- Drafts only: in YouTube Studio, set each from "Draft" to "Unlisted".
  - `sudo uv run python ./scripts/make_video_unlisted_bot_companion.py` may help, but it's an OS bot that needs
    tweaking on your computer.
