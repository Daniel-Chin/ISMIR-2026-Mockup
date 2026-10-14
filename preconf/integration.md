# Integration of the Pre-Conference Lounge into Miniconf

Same shape as [live_overview/integration.md](../live_overview/integration.md). In this document `.` is the repo root.

## Components
- **Static page** (this directory, committed): built into `./preconf/build` and merged into `./build`, then published to GitHub Pages with the miniconf.
- **Backend** (Cloudflare Worker + Durable Objects): sign-in, notes and real-time sync. Its source is kept out of this repo (see `./preconf/.gitignore`) and deployed by hand. The page calls it cross-origin.

## Build paths owned by the lounge
- `./preconf/build/lounge.html`: the page, with its own nav. Linked from the miniconf nav as "Pre-Conference Lounge" (`templates/base.html`).
- `./preconf/build/lounge/`: scripts, styles, the frozen paper data (`data/program.json`), and `site-config.js`, which holds the backend URL.
- Nothing else under `./preconf/build` is written.

## Scripts
Both assume `./preconf` is the current directory.
- `install.sh`: checks for Python 3.9+. There are no other dependencies.
- `build.sh [--mockup]`: reads `./sitedata` (or `./sitedata_mock`) and `./live_overview/overview-source` (for the shared look), then writes the build paths above.
- Order in CI (`.github/workflows/refresh-website.yml`):
  1. `pull_from_google_sheet.py`
  2. `build.sh`
  3. merge `./preconf/build` into `./build`

  Paper data is therefore re-frozen on every refresh.

## Input data
- From `{data_path}`: `config.yml` (`name`, `date`, `timezone`, `miniconf_url`, `official_site_url`, `helpdesk_url`), `papers.csv`, `session_assignment.csv`, `events.csv` (rows titled "Oral Session - N" / "Poster Session - N").
- Only public paper fields are exported. Reviews and raw Drive paths for anything other than PDF/video/poster/slides links are never written to the build.

## Backend URL
- Default: `https://ismir-preconf-test.linliwei3916.workers.dev`. Override with the env var `PRECONF_API_ORIGIN` or `build.sh --api-origin …`.
- The Worker must list the Pages host in its `EXTRA_ORIGINS`.
- The Worker validates rooms and boards by pattern, not against the paper list. Data refreshes therefore never require a backend redeploy.

## Sign-in
- Sign in with Slack (OpenID Connect). "Sign in" on `lounge.html` goes to the Worker, then to Slack's own sign-in page, and back.
- The user id is the Slack user id (with the workspace id); the name is the Slack name.
- The Worker exchanges the code with the Slack app's secret and returns to `lounge.html` with the session in the URL fragment. The page keeps the session in localStorage.
- No secrets are needed by the build or by CI.
