"""Turn sitedata_mock/ into paste-ready tabs for the master Google Sheet.

Reads sitedata_mock/*.csv (from make_example_mock_data.py) plus the Google Drive file
IDs of the uploaded mock PDFs (scripts/mock_drive_ids.json) and writes one
.tsv per sheet tab into sheet_export/. TSV because pasting tab-separated text
into Google Sheets splits into columns automatically; CSV pastes as one column.

The paper media columns are rewritten from repo-local static/mock/ paths to
author-style Drive share links:
    raw_*  -> https://drive.google.com/open?id=<ID>&usp=drive_copy

Usage:
  python scripts/make_sheet_export.py
Then paste each sheet_export/<tab>.tsv into its tab, and point
`pull_from_google_sheet.py` at the sheet to pull them back down as sitedata CSVs.
"""

import csv
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MOCK_DIR = os.path.join(ROOT, "sitedata_mock")
OUT_DIR = os.path.join(ROOT, "sheet_export")

with open(os.path.join(ROOT, "scripts", "mock_drive_ids.json")) as f:
    DRIVE = json.load(f)["files"]


def raw_link(key):
    return f"https://drive.google.com/open?id={DRIVE[key]}&usp=drive_copy"


def transform_papers(row):
    uid = row["uid"]
    for kind, raw_col in [
        ("paper", "raw_pdf_path"),
        ("poster", "raw_poster_pdf"),
        ("slides", "raw_slides_pdf"),
    ]:
        key = f"{kind}_{uid}"
        row[raw_col] = raw_link(key)
    # video stays a YouTube embed URL — the video column accepts any iframe src
    return row


def transform_lbds(row):
    key = f"lbd_{row['uid']}"
    # real LBD data uses open?id= links; main.py converts them to /preview
    row["paper_link"] = raw_link(key)
    row["poster_link"] = raw_link(key)
    return row


def transform_industry(row):
    key = f"sponsor_{row['uid']}"
    row["pdf"] = f"https://drive.google.com/file/d/{DRIVE[key]}/preview"
    return row


TRANSFORMS = {
    "papers": transform_papers,
    "lbds": transform_lbds,
    "industry": transform_industry,
    "events": lambda row: row,
    "music": lambda row: row,
}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for tab, transform in TRANSFORMS.items():
        in_path = os.path.join(MOCK_DIR, f"{tab}.csv")
        out_path = os.path.join(OUT_DIR, f"{tab}.tsv")
        with open(in_path, newline="") as f:
            reader = csv.DictReader(f)
            rows = [transform(dict(r)) for r in reader]
            header = reader.fieldnames
        with open(out_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=header, delimiter="\t")
            writer.writeheader()
            writer.writerows(rows)
        print("wrote", out_path, f"({len(rows)} rows)")
    print("\nPaste each .tsv into its Google Sheet tab (cell A1, Ctrl+V).")


if __name__ == "__main__":
    main()
