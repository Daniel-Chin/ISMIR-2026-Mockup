# YouTube
For hosting 3-min presentation videos.

## Rename and verify local videos
- Use [../scripts/download_and_rename_videos_and_captions.py](../scripts/download_and_rename_videos_and_captions.py)  
- Use [../scripts/police_videos.py](../scripts/police_videos.py) to monitor durations. 
- Use [../scripts/time_stretch_videos.py](../scripts/time_stretch_videos.py)  

## Manually upload videos
- YouTube studio account verification
- Upload the videos to the channel via web browser.  
- Wanna upload more than 10 videos per day?
  - YouTube Studio → Settings → Channel → Feature eligibility → Advanced feature

## Set title, description, captions, and other metadata
- Set up project and app in Google Cloud Console.  
- Use [../scripts/decorate_youtube_videos.py](../scripts/decorate_youtube_videos.py)  

## Set visibility to unlisted
- Try batch edit in YouTube Studio first.
- If batch edit fails, use [../scripts/make_video_unlisted_bot_companion.py](../scripts/make_video_unlisted_bot_companion.py) to semi-manually publish drafts as unlisted.
  - Linux only (evdev/uinput, works on Wayland). Needs access to `/dev/input/*` and `/dev/uinput` (e.g. be in the `input` group, or use sudo). Assumes a US keyboard layout.
  - Install the Vimium browser extension beforehand.
  - Run `uv run --extra youtube python -m scripts.make_video_unlisted_bot_companion` (optionally `--device /dev/input/eventN`, `--debug` to slow down).
  - Loop: click "edit" (pen icon) on a draft → press `2` → wait for the bot to finish.
  - Press `` ` `` to quit immediately.
