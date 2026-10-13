## Cheatsheet
```fish
tmux new -s anno_bot
systemd-inhibit --what=sleep --why='announcement bot' \
    uv run python -m long_running_bots.announcement_bot --mockup
# interact...
# ctrl-B D
tmux new -s self_s_bot
systemd-inhibit --what=sleep --why='self service bot' \
    uv run python -m long_running_bots.self_service_pusher
# interact...
# ctrl-B D
systemd-inhibit --list  # to check locks
# logout.
# ...
# login
tmux attach -t anno_bot
tmux attach -t self_s_bot
```

## Announcement bot shell
The announcement bot runs an interactive shell (`announce>` live, `mockup>` with `--mockup`).
Bot output appears above the prompt while you type. Every command prints the resulting state;
`status` prints it on demand. Mechanics are in the docstring of
[announcement_bot.py](announcement_bot.py).

`{e}` is the event's `uid` in `events.csv`. Times are conference-local.

| Command | Effect |
|---|---|
| `help` | List commands. |
| `status` | Offset, current/next events, upcoming announcements. |
| `whats {e}` / `whats next` | One event: base and adjusted start, what is due, what was posted. |
| `running late by {m}` / `running early by {m}` | Set today's offset to m minutes **relative to the base schedule** (not cumulative). `running late by 0` = back on schedule. Posts "We are running m minutes late." |
| `calibrate {e} to {hh:mm}` (or `{hhmm}`) | Set the offset so event e starts at that time. `next` is rejected; use the uid. If the time looks 12 h early (e.g. `3:10` for a 15:00 event), asks: `y` = 15:10, `n` = as typed. |
| `goto {e}` | Event e starts now (`calibrate {e} to now`). `goto next` only in mockup. |
| `announce` / `skip` | Answer the startup question about announcements missed while the bot was down (auto-skip after 60 s). |
| `+{m}` | `--testing` only: fast-forward fake time by m minutes. |
| Ctrl-D | Quit. |

Typical situations:
- Session k is overrunning and k+1 will start ~15 min late: `running late by 15`.
- Session k+1 actually started: `goto {k+1}`. This pins it, so later offset changes won't move it.
- An event already counted as started (20 min past its adjusted start) but it hasn't actually begun:
  `calibrate {e} to {expected start}`. This unpins it.
- Each offset change posts a short schedule update to #general and corrects announcements already made
  for events that haven't started. While running late, the bot also posts a heads-up at each event's
  original announcement time.
- The offset only applies to the day it was set and resets at the next day.
- In mockup, the current event is assumed to overrun until you type `goto next`.

Rehearse without Slack:
```fish
uv run python -m long_running_bots.announcement_bot --mockup --testing
```
Fake time starts 10 min before the first event; `+{m}` advances it. Posts are printed in ASCII
frames instead of sent. It refuses to start if `SLACK_TOKEN_ANNOUNCEMENT_BOT` is set (env or `.env`).

State (offset, announcement log) is saved in `tmp/announcement_bot_state*.json`, so restarting is safe.

## Splitting recordings by event
Keeping the bot's time correct (`goto`, `calibrate`, `running late`) also auto splits the video
recordings. The bot appends every offset/start change to `tmp/announcement_bot_state*.tape.jsonl`.
```fish
uv run python -m scripts.event_boundaries                 # -> tmp/event_boundaries.txt
# Human: check/edit the boundaries; fill in each `recording | file start time | path` line.
uv run python -m scripts.event_boundaries_to_ffmpeg tmp/event_boundaries.txt > tmp/cut.sh
bash tmp/cut.sh   # outputs "tmp/event_videos/{date} {title}.mp4"
```

## Notes
For ISMIR2026, Daniel Chin is in charge of keeping the process running, by keeping his home desktop always on, and opening ssh for maintenance.  

The announcement bot uses `SLACK_TOKEN_ANNOUNCEMENT_BOT` by default and
`MOCKUP_SLACK_TOKEN_ANNOUNCEMENT_BOT` with `--mockup`. Set both in `.env`.
The self-service bot uses its separate `SLACK_BOT_TOKEN_SELF_SERVICE` and
`SLACK_APP_TOKEN_SELF_SERVICE` credentials; it has no mockup or path flags.

The self-service bot monitors each dispatched website refresh in a background
thread, checking every 15 seconds and posting the final outcome in the command's
channel. It reports cancellation separately (new refreshes can cancel older runs).
After 25 minutes, or three consecutive failed status checks, it posts a link for
manual follow-up. Monitoring is in memory and stops if the bot is restarted.
