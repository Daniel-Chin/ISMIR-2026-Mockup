# Slack integration

Creates public Slack channels for papers, LBDs, music performances, and sponsors,
and private channels for tutorials; writes a deep link back into the CSV's
`channel_url` column (which the site's "Slack" button links to); invites
participants into their channels; and sets paper channel metadata.

## Architecture

```
sitedata/papers.csv ── miniconf_prep.py --action setup-papers-<step>
                              │
                              ▼
                   modules/papers.py (Papers)
                     · generates channel names from session/position/title
                     · orchestrates create → link-writeback → invite → set-desc
                              │
                              ▼
                   utils/slack.py (slack_sdk WebClient, bot token)
                     · channel create / invite / topic+purpose
                     · channel_url written into papers.csv
```

| File | Role |
|---|---|
| `utils/slack.py` | Thin Slack Web API wrapper: channel/user lookups, channel creation, invites, topic/purpose, CSV `channel_url` writeback, rate-limit retry |
| `modules/papers.py` | `Papers`: channel naming (`title2channelID`) and the four paper steps |
| `modules/{lbds,music,industry,tutorials}.py` | Same idea for other content types — see [Non-paper modules](#non-paper-modules) |
| `miniconf_prep.py` | CLI entry point (`--action setup-papers-*`, `setup-event-channels`, `create-event-channels`, `setup-tutorials-*`, `setup-lbd-channels`, `create-lbd-channels`, `setup-music`, `setup-sponsors`) |

## One-time setup (human, ~10 min)

Slack app creation is browser-only. The person must be able to install apps to
the workspace (workspace admin, or an app-approval flow).

1. Create the workspace if needed (a free workspace is fine).  
2. Follow the beginning of ["Operational sequence"](#operational-sequence).  
3. Create an app at <https://api.slack.com/apps?new_app=1> ("From scratch",
   pick the workspace).
   - The "app name" will be shown in Slack channels, so use something like "Service Bot".
4. **OAuth & Permissions → Scopes → Bot Token Scopes**, add:
   - `channels:manage` — create public channels, invite, set topic/purpose
   - `channels:read` — list channels
   - `groups:write` + `groups:read` — create and manage private tutorial channels
     (the bot must be a member to access them)
   - `users:read` + `users:read.email` — resolve author emails to user IDs
   - `chat:write` — post messages (only `postMessageToASlackChannelAsBot`)
   - `pins:write`
   - `channels:join`
   - `channels:history`
   - `groups:history`
   - `mpim:history`
   - `im:history`
5. **OAuth & Permissions → Scopes → User Token Scopes**, add:
   - `chat:write`
6. **Install App to Workspace** and copy the two **OAuth Tokens**
   (`xox?-...`).

   The token must start with `xoxb-` or `xoxp-`. A token beginning with `xoxe`
   (for example, one shown by the Slack CLI or under app configuration tokens)
   is a different credential and is not the bot token expected by this
   repository. Do not put it in `SLACK_BOT_TOKEN`. Return to **OAuth &
   Permissions**, install or reinstall the app, and copy the **Bot User OAuth
   Token** and **User OAuth Token** instead.

7. In the repo root, add to `.env` (already gitignored — never commit it):

   ```
   SLACK_USER_TOKEN=xoxp-...
   SLACK_BOT_TOKEN=xoxb-...
   DUMMY_EMAIL=<your-email-in-that-workspace>   # invite target in non-prod mode
   ZOOM_REDIRECT_ACCESS_TOKEN=<put-random-string-here>
   ```

8. Smoke test (read-only, creates nothing):

   ```bash
   .venv/bin/python -c "from utils import slack; print(len(slack.get_all_channels_data()), 'channels')"
   ```

9. Give a nice profile image to the bot.  

## Running it

```bash
# 1. (optional) regenerate channel names in papers.csv and events.csv from session/position/title
.venv/bin/python miniconf_prep.py --mockup --action setup-papers-setup-channels
.venv/bin/python miniconf_prep.py --mockup --action setup-event-channels

# Manually remove sessions that don't need a channel (e.g. registration, welcome reception)  

# 2. create channels, write channel_url back into papers.csv and events.csv
.venv/bin/python miniconf_prep.py --mockup --action create-event-channels
.venv/bin/python miniconf_prep.py --mockup --action setup-papers-create-channels

# 3. set paper channel topic + purpose (title, authors, program-site URL, poster-session Slack link)
#    Run setup-zoom first: this step requires each poster session's live_url. See ./ZOOM.md
.venv/bin/python miniconf_prep.py --mockup --action setup-papers-set-desc

# 4. set event channel purpose for all event rows
#    Run setup-zoom first: this step requires each event's live_url. See ./ZOOM.md
.venv/bin/python miniconf_prep.py --mockup --action set-event-channel-desc
# This command needs to be run again each time event uid changes (e.g. from adjustment of conference schedule)

# 5. Tutorials.
.venv/bin/python miniconf_prep.py --mockup --action setup-tutorial-channels
.venv/bin/python miniconf_prep.py --mockup --action create-tutorial-channels
# It's normal to not be able to see the channels at this stage --- they are private even to admins. So run the next step:  
.venv/bin/python miniconf_prep.py --mockup --action add-admins-to-tutorials
.venv/bin/python miniconf_prep.py --mockup --action add-registrants-to-tutorials

# 6. LBDs: name channels lbd{uid}-{first-3-title-words} into lbds.csv slack_channel, then create them and write channel_url
.venv/bin/python miniconf_prep.py --mockup --action setup-lbd-channels
.venv/bin/python miniconf_prep.py --mockup --action create-lbd-channels

# 7. invite authors into their paper and LBD channels (non-prod → invites DUMMY_EMAIL instead)
#    Authors from CMT + registration + Slack profiles, see below
.venv/bin/python miniconf_prep.py --action invite-authors-to-channels --prod true \
    [--preferred-emails-csv <csv>] [--registration-csv <csv>] [--cmt-csv local/cmt_authors.csv]
```

Omit `--mockup` for the real conference data and add `--prod true` for
step 7 to invite the real authors. Steps 3 and 4 can run in any order after
step 2; step 7 needs the paper and LBD channels from steps 2 and 6.

After scripts, manual setup include: setting the correct channels to be default; setting channel description.

`SLACK_BOT_TOKEN` is needed for every step that talks to Slack (2–7). Importing
`utils/slack.py` without a token is safe — no API calls are made until needed and the
first actual API call just fails with `invalid_auth` — so step 1
(`setup-channels`), which only rewrites the CSV, runs without credentials.

Channel names are sanitized to lowercase letters, numbers, dashes, or
underscores only. 

### What each step does

**`setup-channels`** (local only, no Slack writes): overwrites the
`slack_channel` column for every row as
`p{session}-{position}-{first-3-words-of-title}` via `title2channelID` —
lowercased, punctuation stripped, `&` → `and`, spaces → `-`. Example:
`p2-1-reformulating-soft-dynamic`. Skip this step if the sheet already carries
final channel names. Session and position come from `session_assignment.csv`.

**`create-channels`**: for every `slack_channel` value not already present in
the workspace (public + private channels the bot can see), creates a public
channel; then writes `https://<workspace>.slack.com/archives/<id>` into the
`channel_url` column for every row whose channel exists (the workspace URL comes
from `auth.test`). The CSV is rewritten in place.

**`invite-authors-to-channels`**: for every paper and LBD channel (by `uid` = CMT ID in `papers.csv` and
`lbds.csv`), adds the Slack members who are its authors and tries to make them channel managers. Authors
are found, in order, by: the paper numbers typed into the registration form; registrants matched to the
paper's CMT authors; and Slack profiles matched to the CMT authors directly. Matching uses
[`utils/identity.py`](../utils/identity.py), weak evidence included (see [IDENTITY.md](IDENTITY.md)). A
registrant reaches Slack through their registration email or their preferred email
(`--preferred-emails-csv`, columns `registration_email`, `preferred_email`). The plan is written to
`tmp/author_channel_invites.csv`, with the evidence for each invite. Registered authors who aren't in
Slack yet are printed, and you're asked to confirm before anything changes. The step only adds people,
so you can re-run it as more people join. Someone who leaves a channel isn't added back (see
[Channel add history](#channel-add-history)). Channel managers go through `admin.roles.addAssignments`
(role `Rl0A`), which probably needs Enterprise Grid. After the first failure the step stops trying and
says so, and you can set managers by hand from the plan file. Without `--prod`, every channel gets only
`DUMMY_EMAIL`.

**`setup-papers-set-desc`**: uses the session number from `session_assignment.csv`
to find the matching oral and poster channels in `events.csv`. Writes the paper
title, page URL, authors, and links to both session channels.

**`set-event-channel-desc`**: updates event metadata for every event row. For each
row it sets the event channel purpose to the session window and Zoom/live URL. If a matching poster
session is missing, if `live_url` is empty, or if the event Slack channel is
absent, the action stops with an error and prints the required prerequisite
(`setup-zoom` and/or event channel creation). The program base URL is
`miniconf_url` from config.yml.

## Workspace setup and tutorial channels

Tutorial channels are created private by `create-tutorial-channels`.

### Operational sequence:

1. Rename the general channel to "#general". 
2. Set `#general` so only managers can post. 
3. Create `#social`, `#random`, and `#help` as **public** channels, and tutorial
   channels as **private** channels before sending workspace invitations.
   Ensure the provisioning bot is a member of the tutorial channels.
4. Go to Workspace Settings.
5. Require admin approval when member invite new people to your workspace.  
6. Remove "Members" from permission to "Use @everyone in channels".  
7. Add `#general`, `#social`, `#random`, `#help`, and the opening session channel
   to Slack's **Default Channels** list as permanent defaults. Keep private
   tutorial channels out of this list; their members will be assigned by script.
8. Disable "Email Display".

### Tutorial invitation workflow

`add-registrants-to-tutorials` adds everyone who registered with the tutorial fee to **every** tutorial
channel. A registrant counts if any of the four fee columns of the registration export (`Virtual Tutorials
(Full Day)`, `Virtual Tutorials (Full Day) - Students`, `Tutorials (Full Day)`, `Tutorials (Full Day) -
Students`) is nonzero. The "Which Tutorial(s) are you planning to attend?" answer and payment status are
ignored. A registrant is found in Slack by their registration email or their preferred email
(`--preferred-emails-csv`), never by name, because these channels are paid. The default export is
`local/registration/Registrant Details - latest.csv` (`--registration-csv` to override). The step prints
registrants not in Slack yet, asks for confirmation, and only adds people, so you can re-run it as people
join; someone who leaves a tutorial channel isn't added back (see [Channel add history](#channel-add-history)).
Without `--prod`, only `DUMMY_EMAIL` is added. `process-new-users` runs this step too.

### Channel add history

`invite-authors-to-channels` and `add-registrants-to-tutorials` record, per channel ID, every user they added
or found already in the channel, in `tmp/channel_add_history.json` (`tmp/channel_add_history_mockup.json` with
`--mockup`). Later runs skip those users, so attendees who quit a channel stay out. To add someone again, add
them by hand in Slack, or delete their ID from the file. Deleting the file resets the history, and the next run
adds everyone again.

### CLI stages

### Workspace constraints

- Adding a channel to the default list does not retroactively add existing
  workspace members. Removing it later does not remove people who already
  joined.
- Keep `#general` and `#help` public and default throughout the
  conference. Restrict posting in `#general` through Slack's channel
  posting permissions.
- Do not make every paper channel a default channel. Paper channels are public
  and discoverable; assign authors directly and let attendees join the papers
  they want to discuss.
- Workspace invitations and invite links expire after 30 days. A shared invite
  link supports up to 400 uses, so a full ISMIR audience may need staged
  invitations. The 2025 retrospective recommends starting early.

Slack UI path for owners/admins:
**Workspace name → Tools & settings → Workspace settings → Default Channels**.
See Slack's current documentation for
[default channels](https://slack.com/help/articles/201898998-Set-default-channels-for-new-members)
and [workspace invitations](https://slack.com/help/articles/201330256-Invite-new-members-to-your-workspace).

# Announcement Bot
See docstring in ../announcement_bot/announcement_bot.py  
We use the #general channel and we do not have an #announcement channel because the free plan can only limit posting permissions in the #general channel.

## Idempotence and the sheet round-trip

Channels are keyed by **name**. `create-channels` checks `isChannel()` before
creating, so re-running never duplicates. This matters because
`python pull_from_google_sheet.py` / `python pull_from_google_sheet.py --mockup`
re-pull the Google Sheet data and overwrite `papers.csv` — including
`channel_url`. The recovery is to re-run `setup-papers-create-channels`:
existing channels are found by name and their URLs backfilled. If the sheet
should stay the source of truth, paste the generated `channel_url` values back
into the sheet after the first real run.

Corollary: **channel names are identity**. Rerunning `setup-channels` after a
title or session/position change in the sheet produces a *new* name, and
`create-channels` then creates a second channel; the old one must be archived
by hand. Once channels exist, treat `slack_channel` as frozen.

`invite-authors-to-channels` and `set-desc` are also safe to re-run: invites skip existing
members, and topic/purpose are simply overwritten.

## Live and mockup credentials

Provisioning uses `SLACK_BOT_TOKEN` and `SLACK_USER_TOKEN` by default. Add
`--mockup` to any `miniconf_prep.py` command to select `MOCKUP_SLACK_BOT_TOKEN`
and `MOCKUP_SLACK_USER_TOKEN`. The announcement bot's `--mockup` selects
`MOCKUP_SLACK_TOKEN_ANNOUNCEMENT_BOT`; otherwise it uses
`SLACK_TOKEN_ANNOUNCEMENT_BOT`. There is no fallback to live credentials.

`--mockup` selects both `sitedata_mock/` and mockup credentials. Without it,
commands use `sitedata/` and live credentials. `--prod` still controls dummy data
and invitation recipients, not the Slack workspace.

For direct Python use, call `utils.slack.configure_clients(is_mockup=True)`
before Slack operations. Switching credentials clears cached channel/user IDs.
The separate LLM and self-service apps retain their own documented credentials.

## utils/slack.py API surface

Importing the module is side-effect free apart from loading `.env`: the
`WebClient` is built with whatever `SLACK_BOT_TOKEN` is present (possibly empty),
and the user/channel lookup maps are fetched from the API **on first use**,
then cached for the life of the process. A missing token surfaces as
`invalid_auth` on the first real call, not at import. All wrapped calls retry
on `ratelimited` (2 s sleep, up to 100 tries) via the `retry` helper.

| Function | Notes |
|---|---|
| `createSlackChannels(channels, is_private=False)` | Creates each name that does not exist yet; tutorials pass `is_private=True` |
| `createPublicSlackChannels(channels)` | Deprecated compatibility wrapper for public-channel creation |
| `createPrivateSlackChannels(csvFile, channelColumnName)` | Legacy private-channel helper that reads names from a CSV column |
| `loadAllChannelData()` | Invalidates the cached channel maps so the next lookup refetches — call after creating channels, before writing links |
| `addChannelLinksToCSV(csvFile, channelColumnName, newCsvFile=None)` | Writes `https://<workspace>.slack.com/archives/<id>` links into a `channel_url` column; in place unless `newCsvFile` given |
| `inviteUserToChannel(user_email, channelName)` / `inviteUsersToChannel(user_emails, channelName)` | Skips users already in the channel; prints and skips emails not in the workspace |
| `updateTopicandPurpose(channelName, topic, purpose)` | Used by `set-desc` |
| `isChannel(name)` / `getChannelID(name)` / `getUserID(email)` / `getUserEmail(id)` | Cache lookups, no API call |
| `memberEmailsAlreadyInChannel(channelName)` | Emails of current members (None entries for bots) |
| `postMessageToASlackChannelAsBot(channel, text)` | Bot must be a member of the channel |

The channel and user caches are filled on first lookup and then reused; a
channel created outside the script (or by another process while this one runs)
is invisible until `loadAllChannelData()` invalidates the cache or the process
restarts.

## Slack platform constraints

- **Channel names**: max 80 chars, lowercase letters/numbers/hyphens/underscores
  only. `conversations_create` rejects anything else (`invalid_name`), and
  returns `name_taken` even when the clashing channel is **archived** —
  unarchive or pick a new name.
- **~90 channels per run**: Slack rate-limits bulk channel creation; the
  ISMIR 2022 run needed multiple passes for 100+ channels. The retry helper
  handles `ratelimited` waits, but budget time for a big first run.
- Channel and user listings use cursor pagination with Slack's recommended
  page size of 200.
- Channel assignments require the target to be an active or pending invited
  workspace member; the Web API cannot invite someone *to the workspace* on a
  non-Enterprise plan, so send workspace invites first.
- The bot can only see private channels it is a member of; `isChannel` may
  report false for a private channel created by someone else, and creation
  then fails with `name_taken`.

## Non-paper modules

`modules/lbds.py`, `modules/music.py`, `modules/industry.py`, and
`modules/tutorials.py` follow the same create → link-writeback → invite flow
for their CSVs. Tutorials delegate private-channel creation and link writeback
to `modules/events.py`, with registered attendee assignment handled separately.
They were ported to the current
`utils/slack.py` signatures in July 2026 — before that they passed
`slackUtils.client` as a first argument and crashed with `TypeError`. They
now also reload channel data between creation and link-writeback, like
`papers.py`. The papers path remains the most exercised one; the non-paper
actions have not been run against a live workspace since the port, so give
them a mock-workspace pass before a real run. LBDs have only
`setup-lbd-channels` / `create-lbd-channels` (no invites); channel names are
`lbd{uid}-{first-3-title-words}`.

## Testing without credentials

Everything up to the first API call works offline: modules import, and
`setup-channels` (pure CSV rewrite) runs with no token at all. Anything that
touches Slack needs a real workspace. The cheapest real test is the mock run
(MOCKUP.md § 2) — a free throwaway
workspace, the 6-row `sitedata_mock/papers.csv`, and non-prod invites going
to `DUMMY_EMAIL`. That exercises create → link-writeback → invite → set-desc
end to end without touching real authors.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `invalid_auth` | `SLACK_BOT_TOKEN` missing/empty (`.env` is read relative to the CWD — run from repo root), token revoked, wrong workspace, or app uninstalled |
| Token starts with `xoxe.xoxp-` | wrong credential type — this project requires the app's `xoxb-` **Bot User OAuth Token** from **OAuth & Permissions** after installation |
| `missing_scope` | a bot scope from the setup list wasn't added, or the app wasn't **reinstalled** after adding scopes |
| `name_taken` on create | channel already exists **archived**, or is a private channel the bot can't see |
| `invalid_name` | uppercase/punctuation in `slack_channel` — regenerate with `setup-channels` |
| `User <email> does not exist in the workspace.` | author not yet a workspace member — workspace invites are manual, then re-run `invite-authors-to-channels` |
| `Rate limit exceeded. Retrying...` loops | expected on bulk runs; Slack caps ~90 channel creations per run |
| `channel_url` empty after the data pull | expected — re-run `setup-papers-create-channels` to backfill |
| `[SSL: CERTIFICATE_VERIFY_FAILED]` | handled — the client pins `certifi`'s CA bundle (`utils/slack.py` top) |
