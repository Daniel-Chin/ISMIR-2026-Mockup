# shared/

Front-end files used by both miniconf add-ons, the Live Overview (`live_overview/`, `live.html`)
and the Warm-up Discussion (`preconf/`, `lounge.html`). Each build copies them in:
`live_overview/scripts/site_files.py` (into `live_overview/`) and `preconf/scripts/build_data.py`
(into `public/vendor/`). Edit them here, never in a build output.

- `site-chrome.js`: the header. Lights Off / On (saved per browser, one setting for both sites) and,
  below 1100px, the nav behind a menu button. Loaded in `<head>` so the theme never flashes.
- `timezone-preference.js`: the "Choose your time zone" picker in the hero.
- `canon-egg.js`: the hidden piano easter egg on the hero, its messages and the list of finders.
  Each page provides `window.PC_EGG` (sign-in, record a find, read the list) and may provide
  `window.PC_EGG_POOL` (papers with a fun fact); see the comment at the top of the file.

The Warm-up Discussion also reuses the Live Overview's stylesheet
(`live_overview/overview-source/styles.css`), so both sites look the same.
