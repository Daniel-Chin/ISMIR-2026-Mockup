# YouTube
For hosting 3-min presentation videos.

The whole job, from the Google Form to the Live Database: [repeatable_workflows.md](repeatable_workflows.md).

## Rename and verify local videos
- Use [../scripts/download_and_rename_videos_and_captions.py](../scripts/download_and_rename_videos_and_captions.py)  
  - Downloads through the Google Drive API (`--uids` for only some papers).
- Use [../scripts/police_videos.py](../scripts/police_videos.py) to monitor durations. 
- Use [../scripts/time_stretch_videos.py](../scripts/time_stretch_videos.py)  
  - Speeds up too-long videos and retimes their captions to match.

## Manually upload videos
- YouTube studio account verification
- Upload the videos to the channel via web browser.  
  - Title: the file name (paper uid). Description: empty. Visibility: Unlisted.
  - `decorate_youtube_videos.py --upload` can upload through the API instead, at a large quota cost per video.
- Wanna upload more than 10 videos per day?
  - YouTube Studio → Settings → Channel → Feature eligibility → Advanced feature

## Set title, description, captions, and other metadata
- Set up project and app in Google Cloud Console.  
- Use [../scripts/decorate_youtube_videos.py](../scripts/decorate_youtube_videos.py)  
  - Prints the planned changes and asks before applying them; then writes the new `video` links to the Live
    Database, after confirmation.

## Set visibility to unlisted
- Try batch edit in YouTube Studio first.
- If batch edit fails, use [../scripts/make_video_unlisted_bot_companion.py](../scripts/make_video_unlisted_bot_companion.py) to semi-manually publish drafts as unlisted.
  - Linux only (evdev/uinput, works on Wayland). Needs access to `/dev/input/*` and `/dev/uinput` (e.g. be in the `input` group, or use sudo). Assumes a US keyboard layout.
  - Install the Vimium browser extension beforehand.
  - Run `uv run --extra youtube python -m scripts.make_video_unlisted_bot_companion` (optionally `--device /dev/input/eventN`, `--debug` to slow down).
  - Loop: click "edit" (pen icon) on a draft → press `2` → wait for the bot to finish.
  - Press `` ` `` to quit immediately.
