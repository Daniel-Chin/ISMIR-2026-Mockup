# Sponsors

The Industry event page (`event_industry-panel.html`, the target of the nav bar's "Industry" button) shows sponsor logos by tier, below the event description.

## Where the data lives

`sitedata/sponsors/` holds this conference's sponsor data. Unlike the rest of `sitedata/` (sheet exports, gitignored), it is committed, because it is maintained by hand rather than pulled from the Google Sheet.

- `sponsors.yml` — tiers in display order, each with its sponsors (`name`, `logo` filename, `url`).
- Logo images, referenced by `logo`.

Source: <https://ismir2026.ismir.net/meet-the-sponsors>. Only sponsorship tiers are included; strategic partners and donors are left out.

## How it's wired

- `main()` in `main.py` loads `<site_data_path>/sponsors/sponsors.yml` if it exists; without it, no sponsors are shown.
- The `event` route passes the tiers to `templates/event.html` only for the event with category `Industry`.
- Logos are served at `/sponsors/<file>` by `send_sponsor_logo`, and the freezer generator yields each logo listed in the YAML.

## Updating

1. Download the original logo (strip the `thumbnail_` prefix from the image URL on the sponsors page for full resolution).
2. Shrink it if it's large: logos display at most 60px tall, so 800px wide is plenty (`PIL`: resize to width 800, `optimize=True`; quantize PNGs to 256 colours).
   If it is dark on a transparent background (currently Moises), flatten it onto white with ~12% padding: Dark Reader darkens the page (including CSS backgrounds) but not images, so such logos become invisible.
3. Save it in `sitedata/sponsors/` and add an entry to `sponsors.yml`.

For a new conference, replace the directory contents.

## Official notes on the Warm-up's Industry Board

A sponsor's reps can tick **Official note from …** when they post on the Industry Board. They pick their own sponsor, and the other choices are greyed out. An official note is white with a red tack, like a pinned paper, and is signed with the sponsor's name, not the rep's. It belongs to the sponsor: any of its reps can edit, move or delete it. Nobody else can, except moderators, who can also post official notes for any sponsor, for example to test. There is no cap on how many a sponsor posts. Notes start inside the sponsor's area but can be moved anywhere. The server enforces these rules in `preconf/src/board-core.js`.

**Who is a rep.** A Live Database tab lists the reps.
- Each row starts with the sponsor (its first word is the Warm-up id: `moises`, `adobe research`, `anghami`), followed by its reps' emails, one per column, as many as needed.
- A row starting with `admin` lists moderators.

**How the Worker reads it.** The Worker reads the tab's CSV export itself; `SPONSOR_REPS_SHEET` in `preconf/wrangler.jsonc` holds the URL. Sign-in gives only a Slack id, so the Worker looks each email up with its own Slack bot token. That token is the Warm-up Slack app's and needs the `users:read.email` scope. The Worker keeps the result for a minute (`sheetReps` in `preconf/src/auth.js`). No token leaves Cloudflare, and no list is published. If a Slack lookup fails, for example because the scope is missing, the Worker keeps its last list and does not use a partial one.

**To change reps:** edit the tab. It takes effect within a minute; open boards pick it up when they reconnect. To preview what the Worker will find, run `python scripts/sync_sponsor_reps.py`.
