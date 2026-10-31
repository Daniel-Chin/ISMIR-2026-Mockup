# Live Overview ↔ Miniconf integration

How Live Overview fits into the miniconf build. In this document `.` is the repo root.

## Components
- **Static page**: built into `./live_overview/build/`, merged into the miniconf `./build/`.
- **Backend** (Cloudflare Worker, source not yet in this repo):
  - Holds the Zoom API credentials, caches responses, rate limits, and serves live state (`/api/state`, WebSocket) to browsers over CORS.
  - Maps event `uid` to Zoom meeting or webinar ID using the non-public `live_url` in `events.csv`, and maps poster breakout rooms to papers (paper aliases).
  - Uses event start and end times to poll only meetings that are live, decides each event's `live`/`upcoming`/`history` status, keeps peak headcounts after an event ends, and runs the test clock (set on its own `admin.html`; every page then shows that time).
  - Production: the Worker at `live_overview_api` in `config.yml`. `LIVE_OVERVIEW_API_ORIGIN` (or `--api-origin`) overrides it.
- **Easter egg sign-in**: the hidden piano's finders list and Slack sign-in use the Warm-up Discussion's backend (`warmup_api` in `config.yml`, see `./preconf/integration.md`). The page has no Sign in button; the egg's message offers it.
  - Schedule push: `build.sh` uploads the full schedule, raw `live_url`s included, via `/api/admin/import`. This happens only when `LIVE_OVERVIEW_ADMIN_KEY` is set and there are no sheet problems, and it is skipped when nothing changed. `./sitedata` goes to the production backend, sheet problems blocking it; `--mockup` goes to the rehearsal backend, whatever its problems, and refuses the production one. The push isn't ideal, but we keep it while the backend lives outside the repo.

## URLs
- `prefix` = `miniconf_url` in `config.yml` (`https://ismir2026program.ismir.net` or `https://daniel-chin.github.io/ISMIR2026-Kit`).
- The page is `{prefix}/live.html`, linked directly from the miniconf nav (`templates/base.html`). 
  - It keeps its own nav bar (with the light switch). "Mini Conf" links to `{prefix}` and "Official Website" to `official_site_url`.

## Build outputs
Live Overview owns only:
- `./live_overview/build/live.html`: the page.
- `./live_overview/build/live-debug.html`: the same page for testing (see *Testing features* below). Not linked from anywhere.
- `./live_overview/build/live_overview/`:
  - JS/CSS assets.
  - `public-site-config.js`: build-time settings for the page. It holds the two backend URLs, the conference info copied from `config.yml`, and the location of `schedule-snapshot.json`.
  - Every link carries `?v=<hash of the shipped files>`, so a new build is never run against cached old files.
  - `schedule-snapshot.json`: the schedule with links and live data removed. The page shows it until the backend responds.

It must not write anything else under `./live_overview/build`.

## Input data
`data_path = ./sitedata | ./sitedata_mock`.  
- `events.csv`: events keyed by `uid`.
- `papers.csv`: paper metadata. 
- `session_assignment.csv`: each paper's session and position. Parsed in Python by `scripts/update_schedule.py:convert`, which follows `utils/session_assignment.py`.
- `config.yml`: `name`, `date`, `timezone`, `miniconf_url`, `official_site_url`, `live_overview_api`, `warmup_api` and `slack_app_name`. All conference-specific text and URLs come from here; nothing is hardcoded and there's no timezone default. For a new year, edit `config.yml` (and deploy the backends); no code changes.

No secrets are needed to build the page. `LIVE_OVERVIEW_ADMIN_KEY` only enables the backend push.

Data refresh (`git pull`, `uv run python pull_from_google_sheet.py`) is the caller's job.

## Zoom
- The page never shows or links a real Zoom URL.
- An event's Zoom button always links to `{prefix}/zoom.html?event_uid={uid}` (built in `overview-source/site-integration.js`). Papers never get Zoom links.
- The static snapshot contains no Zoom, Slack or other `links`. Raw `live_url`s go only to the backend push.

## Event pages
- Event titles link to the event's miniconf page (`detailUrl`, e.g. `{prefix}/event_opening-session.html`; oral/poster sessions go to `papers.html?session=…`). `update_schedule.py` takes it from `event_link` in `./utils/shared.py`, the same rule the miniconf calendar uses; events without a page (Registration, Lunch, …) get no link.

## Files and scripts
- Live Overview owns all of `./live_overview`, including its uv env (`pyproject.toml`).
- `install.sh` runs `uv sync`. `build.sh` builds into `./live_overview/build` (`--mockup` reads `sitedata_mock` and pushes to the rehearsal backend, see [MOCKUP.md](../docs/MOCKUP.md)). Both run from `./live_overview`.
- The caller runs, in order: `pull_from_google_sheet.py` → `install.sh`/`build.sh` → merge `./live_overview/build` into `./build`.
- Miniconf build path: `./live_overview/scripts/build_miniconf.py` (entry point), `./live_overview/scripts/update_schedule.py:convert`, `./live_overview/scripts/csv_helpers.py`, and `./live_overview/scripts/site_files.py` (what ships, the snapshot, the version hash).
- Page code (`overview-source/`): `app.js` (live page), `history.js` (history page), `overview-common.js` (what both use), `public-connection.js` (data from the backend), `egg-account.js` (sign-in for the egg). From `./shared/` (also used by the Warm-up Discussion): `site-chrome.js` (theme and menu button), `timezone-preference.js`, `canon-egg.js`.
- `extra-events.json`: events shown only on the Live Overview (not in `events.csv`, so not on the miniconf). Their Zoom links are set on the backend's admin page, never here (the repository is public).
- Kept but not in the build path: the standalone GitHub Pages exporter (`build_public_site.py`) and the CLI half of `update_schedule.py`.

## Behaviour notes
- The timezone isn't saved; it always defaults to the system timezone, the same as miniconf. The light/dark theme *is* saved (`localStorage`).
- URL params: the page doesn't use the query string. Hash anchors (`#live-events`, …) are used for in-page navigation.

## Testing features
- `live-debug.html` is built from the same `index.html` as `live.html`; the build only adds `data-channel="debug"`, a `[DEBUG]` title and `noindex` (`build_miniconf.debug_page`, checked by `test/test_debug_page.py`).
- Features under test are listed in `overview-source/features.js` with stage `'debug'` and asked for in code as `ismirFeature('name')`. They are on in `live-debug.html` only.
- Shipping one to `live.html`: change its stage to `'live'` in `features.js`. Both pages run the same code, so nothing is copied and nothing can be missed. Once it has been live for a while, the check and the entry can be removed together (`test/features.test.cjs` fails while either is left alone).
- The organisers' test clock (`admin.html`) applies to `live-debug.html` only. `live.html` and `history.html` always show real time, and the backend's public statuses follow real time; while the test clock is on, sessions live at the test time also accept observers and serve their Zoom links, so they can be tested.
