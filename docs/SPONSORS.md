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
   If it is dark on a transparent background (currently Moises and Audible Magic), flatten it onto white with ~12% padding: Dark Reader darkens the page (including CSS backgrounds) but not images, so such logos become invisible.
3. Save it in `sitedata/sponsors/` and add an entry to `sponsors.yml`.

For a new conference, replace the directory contents.
