import argparse
import os
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib import request

from scripts.calendar_csv2ics import calendar_csv2ics

import dotenv

REAL_SHEETS = {
    "industry": "INDUSTRY_SHEET_URL",
    "papers": "PAPERS_SHEET_URL",
    "events": "EVENTS_SHEET_URL",
    "music": "MUSIC_SHEET_URL",
    "lbds": "LBDS_SHEET_URL",
    "session_assignment": "SESSION_ASSIGNMENT_SHEET_URL",
}
# Downloaded when set, skipped silently otherwise (no prompt, so CI never waits on them).
# lbds_grouping: group_id, theme, channel_url; the LBDs' group_id (lbds.csv) points here.
OPTIONAL_SHEETS = {
    "lbds_grouping": "LBDS_GROUPING",
}

MOCK_SHEETS = {
    "papers"  : "https://docs.google.com/spreadsheets/d/1hak92WcsA16PaXI3TY563NSuCHoe2_PkcWcly9hBTTI/export?format=csv",
    "events"  : "https://docs.google.com/spreadsheets/d/1jJ9hRrVKQu1PozjSnoG60Qsj2RsOylpob4nWfdm_OsE/export?format=csv",
    "lbds"    : "https://docs.google.com/spreadsheets/d/1F6vdNHiDpQKpO5PZ9Yfhv7sB5s_3xtS9i8za-besVl4/export?format=csv",
    "music"   : "https://docs.google.com/spreadsheets/d/1GsqtA27aaHBHqQj1JqNKR_hK9A9lQcy5fUTlq3vWGYM/export?format=csv",
    "industry": "https://docs.google.com/spreadsheets/d/1DmTd2bbcZDxUPWGzOwfADnwQ9bswYmDM5uxu62ui4Qw/export?format=csv",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Download site-data CSVs, rebuild the calendar, and prepare the sitedata "
            "for either the production conference or the mock conference."
        )
    )
    parser.add_argument(
        "--mockup",
        action="store_true",
        help=(
            "Use the mock-conference spreadsheet IDs in sitedata_mock/. "
            "The mock setup stores each tab in a separate Google Sheet and "
            "requires the Drive folder to be shared as 'Anyone with the link: Viewer'."
        ),
    )
    parser.add_argument(
        "--skip-download",
        action="store_true",
        help=(
            "Skip downloading CSVs from Google Sheets."
        ),
    )
    return parser.parse_args()


def download_csv_from_google_sheet(export_url: str, output_path: Path) -> None:
    """Download a published CSV export from a Google Sheet URL.

    The real conference has one master sheet with six tabs. The mock conference uses
    separate Drive sheets instead for historical reasons. In both
    cases the workflow is identical: request the CSV export and save it to a local data dir.
    """
    if not export_url:
        raise ValueError(f"Missing Google Sheet export URL for {output_path.name}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with request.urlopen(export_url) as response, open(output_path, "wb") as file_handle:
        file_handle.write(response.read())

    print(f"downloaded {output_path}")


def get_sheet_mapping(mockup: bool) -> dict[str, str]:
    if mockup:
        return MOCK_SHEETS

    mapping = {}
    for name, env_name in REAL_SHEETS.items():
        env_var = os.getenv(env_name)
        if not env_var:
            print(
                "Missing env var for production sheet download: "
                f"{name}. Set the corresponding *_SHEET_URL value."
            )
            input('Continue anyway? Enter...')
            continue
        mapping[name] = build_csv_export_url_from_sheet_url(env_var)
    for name, env_name in OPTIONAL_SHEETS.items():
        if os.getenv(env_name):
            mapping[name] = build_csv_export_url_from_sheet_url(os.getenv(env_name))
    return mapping

def build_csv_export_url_from_sheet_url(sheet_url: str) -> str:
    """Build a CSV export URL from a pasted Google Sheet tab URL."""
    parsed = urlparse(sheet_url.strip())
    if "google.com" not in parsed.netloc:
        raise ValueError(f"Not a Google Sheets URL: {sheet_url}")

    parts = [p for p in parsed.path.split("/") if p]
    try:
        sheet_id = parts[parts.index("d") + 1]
    except (ValueError, IndexError):
        raise ValueError(f"Missing sheet ID in sheet URL: {sheet_url}") from None

    query_gid = parse_qs(parsed.query).get("gid", [None])[0]
    fragment_gid = parse_qs(parsed.fragment).get("gid", [None])[0]
    if query_gid and fragment_gid:
        assert query_gid == fragment_gid, (
            "gid mismatch between query and fragment in sheet URL: "
            f"{sheet_url}"
        )

    tab_gid = query_gid or fragment_gid
    if not tab_gid:
        raise ValueError(f"Missing gid in sheet URL: {sheet_url}")
    if not tab_gid.isdigit():
        raise ValueError(f"gid must be numeric in sheet URL: {sheet_url}")

    return (
        f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={tab_gid}"
    )


def pull_data_dir(target_dir: Path, mockup: bool) -> Path:
    sheet_map = get_sheet_mapping(mockup)

    for name, export_url in sheet_map.items():
        output_path = target_dir / f"{name}.csv"
        download_csv_from_google_sheet(export_url, output_path)

    return target_dir


def rebuild_calendar_for_data_dir(data_dir: Path) -> None:
    """Rebuild the downloadable ICS calendar from the freshest events CSV."""
    events_csv = data_dir / "events.csv"

    if not events_csv.exists():
        raise FileNotFoundError(f"Missing events CSV at {events_csv}")

    calendar_csv2ics(in_csv=str(events_csv))
    print("calendar rebuilt")


def main():
    dotenv.load_dotenv()

    args = parse_args()

    target_dir = Path("sitedata_mock" if args.mockup else "sitedata")
    if not args.skip_download:
        pull_data_dir(target_dir, args.mockup)
    rebuild_calendar_for_data_dir(target_dir)


if __name__ == "__main__":
    main()
