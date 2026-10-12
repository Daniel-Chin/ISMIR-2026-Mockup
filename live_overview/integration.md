# Live Overview ↔ Miniconf integration

How Live Overview fits into the miniconf build. In this document `.` is the repo root.

## Components
- **Static page**: built into `./live_overview/build/`, merged into the miniconf `./build/`.
- **Backend** (Cloudflare Worker, source not yet in this repo):
  - Holds the Zoom API credentials, caches responses, rate limits, and serves live state (`/api/state`, WebSocket) to browsers over CORS.
  - Maps event `uid` to Zoom meeting or webinar ID using the non-public `live_url` in `events.csv`, and maps poster breakout rooms to papers (paper aliases).
  - Uses event start and end times to poll only meetings that are live, decides each event's `live`/`upcoming`/`history` status, keeps peak headcounts after an event ends, and runs the debug clock.
  - Production: the Worker at `DEFAULT_API_ORIGIN` in `scripts/build_miniconf.py` is this year's production backend. `LIVE_OVERVIEW_API_ORIGIN` overrides it.
  - Schedule push: `build.sh` uploads the full schedule, raw `live_url`s included, via `/api/admin/import`. This happens only when `LIVE_OVERVIEW_ADMIN_KEY` is set and the data is production `./sitedata` with no sheet problems, and it is skipped when nothing changed. The push isn't ideal, but we keep it while the backend lives outside the repo.

## URLs
- `prefix` = `miniconf_url` in `config.yml` (`https://ismir2026program.ismir.net` or `https://daniel-chin.github.io/ISMIR2026-Kit`).
- The page is `{prefix}/live.html`, linked directly from the miniconf nav (`templates/base.html`). 
  - It keeps its own nav bar (with the light switch). "Mini Conf" links to `{prefix}` and "Official Website" to `official_site_url`.

## Build outputs
Live Overview owns only:
- `./live_overview/build/live.html`: the page.
- `./live_overview/build/live_overview/`:
  - JS/CSS assets.
  - `public-site-config.js`: build-time settings for the page. It holds the backend URL, the conference info copied from `config.yml`, and the location of `schedule-snapshot.json`.
  - `schedule-snapshot.json`: the schedule with links and live data removed. The page shows it until the backend responds.

It must not write anything else under `./live_overview/build`.

## Input data
`data_path = ./sitedata | ./sitedata_mock`.  
- `events.csv`: events keyed by `uid`.
- `papers.csv`: paper metadata. 
- `session_assignment.csv`: each paper's session and position. Parsed in Python by `scripts/update_schedule.py:convert`, which follows `utils/session_assignment.py`.
- `config.yml`: `name`, `date`, `timezone`, `miniconf_url` and `official_site_url`. All conference-specific text and URLs come from here; nothing is hardcoded and there's no timezone default.

No secrets are needed to build the page. `LIVE_OVERVIEW_ADMIN_KEY` only enables the backend push.

Data refresh (`git pull`, `uv run python pull_from_google_sheet.py`) is the caller's job.

## Zoom
- The page never shows or links a real Zoom URL.
- An event's Zoom button always links to `{prefix}/zoom.html?event_uid={uid}` (built in `overview-source/site-integration.js`). Papers never get Zoom links.
- The static snapshot contains no links at all. Raw `live_url`s go only to the backend push.

## Files and scripts
- Live Overview owns all of `./live_overview`, including its uv env (`pyproject.toml`).
- `install.sh` runs `uv sync`. `build.sh` builds into `./live_overview/build` (`--mockup` reads `sitedata_mock`). Both run from `./live_overview`.
- The caller runs, in order: `pull_from_google_sheet.py` → `install.sh`/`build.sh` → merge `./live_overview/build` into `./build`.
- Miniconf build path: `./live_overview/scripts/build_miniconf.py` (entry point), `./live_overview/scripts/update_schedule.py:convert`, `./live_overview/scripts/csv_helpers.py`, and `PUBLIC_RELEASE`/`ASSETS`/`snapshot` from `./live_overview/scripts/build_public_site.py`.
- Kept but not in the build path: the standalone GitHub Pages exporter (`build_public_site.build`/`main`), the CLI half of `update_schedule.py`, and the debug-clock code in `app.js`/`history.js` (it runs only on the backend-hosted page). Their docstrings say so. We'll revisit them once the backend source is available.

## Behaviour notes
- The timezone isn't saved; it always defaults to the system timezone, the same as miniconf. The light/dark theme *is* saved (`localStorage`).
- URL params: the static page doesn't use the query string. The debug clock (`?debug=`) only works on the backend-hosted page and isn't in the static HTML. Hash anchors (`#live-events`, …) are used for in-page navigation.
