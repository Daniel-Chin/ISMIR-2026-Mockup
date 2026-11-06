"""Download Google Drive images embedded in sheet text so GitHub Pages can serve them.

Scans the markdown cells in MARKDOWN_COLUMNS for image links
like ![Alt](https://drive.google.com/file/d/ID/view), downloads each into a cache
dir with a URL -> filename map (url_map.json), and copies them plus the map to
static/site_images/. main.py's markdown filter rewrites those URLs to the local
copies. Caching and rate-limit handling are shared with
download_paper_thumbnails.py.

Usage:
  python scripts/download_site_images.py [--mockup]
"""

import argparse
import csv
import json
import re
import shutil
from pathlib import Path

import download_paper_thumbnails as dl

ROOT = dl.ROOT
# Sheet cells that may embed Drive images as markdown.
MARKDOWN_COLUMNS = {"events.csv": ["event_desc"]}
CACHE_DIR = ROOT / ".cache" / "drive_site_images"
OUT_DIR = ROOT / "static" / "site_images"
MARKDOWN_IMAGE = re.compile(r"!\[[^\]]*\]\(\s*<?([^)\s>]+)")


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--mockup", action="store_true", help="Use sitedata_mock/")
    args = parser.parse_args()

    dl.CACHE_DIR = CACHE_DIR  # the shared helpers read this global
    sitedata = ROOT / ("sitedata_mock" if args.mockup else "sitedata")
    urls: list[tuple[str, str]] = []  # (where, url)
    for name, columns in MARKDOWN_COLUMNS.items():
        path = sitedata / name
        if not path.exists():
            continue
        with open(path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                for column in columns:
                    for url in MARKDOWN_IMAGE.findall(row.get(column) or ""):
                        if dl.drive_file_id(url):
                            urls.append((f"{name} uid {row.get('uid')}", url))

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in OUT_DIR.iterdir():
        if stale.name != ".gitkeep":
            stale.unlink()

    url_map = dl.load_url_map()
    used: dict[str, str] = {}
    n_cached = n_downloaded = n_failed = 0
    for where, url in urls:
        if url in url_map:
            n_cached += 1
        else:
            file_id = dl.drive_file_id(url)
            print(f"downloading image for {where} ({file_id})", flush=True)
            path = dl.download(file_id, url)
            if path is None:
                n_failed += 1
                continue
            url_map[url] = path.name
            dl.save_url_map(url_map)
            n_downloaded += 1
        used[url] = url_map[url]

    for filename in set(used.values()):
        shutil.copyfile(CACHE_DIR / filename, OUT_DIR / filename)
    (OUT_DIR / dl.MAP_NAME).write_text(json.dumps(used, indent=1, sort_keys=True))
    print(f"site images: {n_cached} from cache, {n_downloaded} downloaded, {n_failed} failed")


if __name__ == "__main__":
    main()
