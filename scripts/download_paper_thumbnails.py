"""Download paper and LBD thumbnails from Google Drive so GitHub Pages can serve them.

Reads the thumbnail column of <sitedata>/papers.csv (`raw_thumbnail` in the real
sheet, `thumbnail` in the mock one) and of <sitedata>/lbds.csv if present
(`raw_thumbnail_path`), downloads each public Drive file into a
cache dir, and records a URL -> filename map in the cache (url_map.json). The
cached files and the map are copied to static/paper_images/, where main.py looks
up each paper's thumbnail URL. URLs already in the map are never requested
again, so the CI cache (.github/workflows/refresh-website.yml) avoids duplicate
requests to Google.

If Google rate-limits us, wait 5 minutes and retry. Abort if any thumbnail is
over 1 MB.

Usage:
  python scripts/download_paper_thumbnails.py [--mockup]
"""

import argparse
import csv
import json
import mimetypes
import shutil
import time
from pathlib import Path
from urllib import error, request
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
CACHE_DIR = ROOT / ".cache" / "drive_thumbnails"
OUT_DIR = ROOT / "static" / "paper_images"
MAP_NAME = "url_map.json"
THUMBNAIL_COLUMNS = ("raw_thumbnail", "raw_thumbnail_path", "thumbnail")
RATE_LIMIT_WAIT_SECONDS = 5 * 60
MAX_RATE_LIMIT_RETRIES = 6
MAX_BYTES = 1_000_000


def drive_file_id(url: str) -> str | None:
    parsed = urlparse(url.strip())
    if "drive.google.com" not in parsed.netloc:
        return None
    file_id = parse_qs(parsed.query).get("id", [None])[0]
    if file_id:
        return file_id
    parts = [p for p in parsed.path.split("/") if p]
    if "d" in parts and parts.index("d") + 1 < len(parts):
        return parts[parts.index("d") + 1]
    return None


def load_url_map() -> dict[str, str]:
    path = CACHE_DIR / MAP_NAME
    if not path.exists():
        return {}
    url_map = json.loads(path.read_text())
    return {u: f for u, f in url_map.items() if (CACHE_DIR / f).exists()}


def save_url_map(url_map: dict[str, str]) -> None:
    # Saved after every download, so partial progress survives a failed job.
    tmp = CACHE_DIR / (MAP_NAME + ".part")
    tmp.write_text(json.dumps(url_map, indent=1, sort_keys=True))
    tmp.replace(CACHE_DIR / MAP_NAME)


def is_rate_limited(status: int, body: bytes) -> bool:
    if status == 429:
        return True
    text = body[:20000].decode("utf-8", errors="ignore").lower()
    return status in {403, 503} and any(
        s in text for s in ("rate limit", "quota", "too many", "automated queries")
    )


def fetch(file_id: str) -> tuple[bytes, str]:
    url = f"https://drive.google.com/uc?export=download&id={file_id}"
    for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
        try:
            with request.urlopen(url, timeout=60) as response:
                return response.read(), response.headers.get_content_type()
        except error.HTTPError as e:
            status = e.code
            if not is_rate_limited(status, e.read()) or attempt == MAX_RATE_LIMIT_RETRIES:
                raise
        print(
            f"Rate limited by Google (HTTP {status}) on {file_id}. "
            f"Pausing {RATE_LIMIT_WAIT_SECONDS // 60} min before continuing...",
            flush=True,
        )
        time.sleep(RATE_LIMIT_WAIT_SECONDS)
    raise AssertionError("unreachable")


def check_size(n_bytes: int, what: str) -> None:
    if n_bytes > MAX_BYTES:
        raise SystemExit(
            f"ABORT: thumbnail {what} is {n_bytes:,} bytes, over the "
            f"{MAX_BYTES:,}-byte limit. Ask the authors for a smaller image."
        )


def download(file_id: str, url: str) -> Path | None:
    body, content_type = fetch(file_id)
    if not content_type.startswith("image/"):
        # Usually an HTML page: file not shared publicly, or deleted.
        print(f"WARNING: {file_id} is not an image ({content_type}); skipped")
        return None
    check_size(len(body), url)
    ext = mimetypes.guess_extension(content_type) or ".img"
    path = CACHE_DIR / f"{file_id}{ext}"
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(body)
    tmp.replace(path)  # atomic, so a killed job never caches a truncated file
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--mockup", action="store_true", help="Use sitedata_mock/")
    args = parser.parse_args()

    sitedata = ROOT / ("sitedata_mock" if args.mockup else "sitedata")
    rows = []  # (kind, row)
    for kind, name in (("paper", "papers.csv"), ("LBD", "lbds.csv")):
        path = sitedata / name
        if kind == "LBD" and not path.exists():
            continue
        with open(path, newline="", encoding="utf-8") as f:
            rows += [(kind, row) for row in csv.DictReader(f)]

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in OUT_DIR.iterdir():
        if stale.name != ".gitkeep":
            stale.unlink()

    url_map = load_url_map()
    used: dict[str, str] = {}
    n_cached = n_downloaded = n_missing = 0
    for kind, row in rows:
        url = next((row[c].strip() for c in THUMBNAIL_COLUMNS if row.get(c)), "")
        if not url:
            n_missing += 1
            continue
        if url in url_map:
            n_cached += 1
        else:
            file_id = drive_file_id(url)
            if not file_id:
                print(f"WARNING: {kind} {row['uid']}: not a Drive link: {url!r}")
                n_missing += 1
                continue
            print(f"downloading thumbnail for {kind} {row['uid']} ({file_id})", flush=True)
            path = download(file_id, url)
            if path is None:
                n_missing += 1
                continue
            url_map[url] = path.name
            save_url_map(url_map)
            n_downloaded += 1
        check_size((CACHE_DIR / url_map[url]).stat().st_size, url)
        used[url] = url_map[url]

    for filename in set(used.values()):
        shutil.copyfile(CACHE_DIR / filename, OUT_DIR / filename)
    (OUT_DIR / MAP_NAME).write_text(json.dumps(used, indent=1, sort_keys=True))
    print(
        f"thumbnails: {n_cached} from cache, {n_downloaded} downloaded, "
        f"{n_missing} missing"
    )


if __name__ == "__main__":
    main()
