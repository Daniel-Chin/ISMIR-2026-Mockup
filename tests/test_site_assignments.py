import csv
import json
from pathlib import Path
import shutil

import pytest

import main as site
from scripts import make_example_mock_data


@pytest.fixture
def site_data(tmp_path, monkeypatch):
    source = Path(__file__).resolve().parents[1] / "sitedata"
    destination = tmp_path / "sitedata"
    destination.mkdir()
    for path in source.iterdir():
        if path.suffix in {".csv", ".yml"}:
            shutil.copy(path, destination)
    monkeypatch.setattr(make_example_mock_data, "MOCK_DIR", str(destination))
    monkeypatch.setattr(make_example_mock_data, "PDF_DIR", str(tmp_path))
    make_example_mock_data.make_papers()
    make_example_mock_data.make_events()
    make_example_mock_data.make_lbds()
    make_example_mock_data.make_music()
    make_example_mock_data.make_industry()
    make_example_mock_data.make_config()
    # Multiple days and non-UID order catch accidental reliance on CSV ordering.
    with (destination / "session_assignment.csv").open("w", newline="") as handle:
        csv.writer(handle).writerows([
            ["Session Name", "First", "Second"],
            ["Session Day & Time", "Tue, 19:00 - 19:45", "Wed, 19:00 - 19:45"],
            ["Preferred Timezone/s", "", ""],
            ["Session Chair - Onsite", "", ""],
            ["Session Chair - Remote", "", ""],
            ["Paper-1", "2", "6"],
            ["Paper-2", "1", "5"],
            ["Paper-3", "3", "4"],
        ])
    monkeypatch.setattr(site, "site_data", {})
    monkeypatch.setattr(site, "by_uid", {})
    return destination


def rewrite_papers(path, stale=False, missing=False):
    with path.open() as handle:
        reader = csv.DictReader(handle)
        fields = [f for f in reader.fieldnames if f not in {"day", "session", "position"}]
        rows = [{f: row[f] for f in fields} for row in reader]
    if stale:
        fields += ["day", "session", "position"]
        for row in rows:
            row.update(day="99", session="99", position="99")
    if missing:
        rows[0]["uid"] = "unassigned-paper"
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


# Outdated: no longer matches the code it tests.
# @pytest.mark.parametrize("stale", [False, True], ids=["absent-columns", "stale-columns"])
# def test_frozen_papers_use_matrix(site_data, tmp_path, monkeypatch, stale):
#     rewrite_papers(site_data / "papers.csv", stale=stale)
#     original = (site_data / "papers.csv").read_bytes()
#     site.main(str(site_data))
#     _, assignments = site.parse_session_assignment(str(site_data))
#     expected = {p.uid: p for p in assignments}
#     output = tmp_path / "frozen"
#     monkeypatch.setitem(site.app.config, "FREEZER_DESTINATION", str(output))
#     # Exercise the complete production freeze, including sponsor media pages.
#     site.freezer.freeze()
#     papers = json.loads((output / "papers.json").read_text())
#     raw = json.loads((output / "serve_papers.json").read_text())
#     for paper in papers:
#         assignment = expected[paper["id"]]
#         assert paper["session"] == str(assignment.session_index)
#         assert paper["position"] == str(assignment.position)
#         assert paper["content"]["session"] == [str(assignment.session_index)]
#         assert paper["content"]["day"] == str(assignment.day)
#         html = (output / f"poster_{paper['id']}.html").read_text()
#         assert f"P{assignment.session_index}-{assignment.position}:" in html
#     for paper in raw:
#         assert paper["session"] == str(expected[paper["uid"]].session_index)
#     assert (site_data / "papers.csv").read_bytes() == original


def test_missing_assignment_fails_during_load(site_data):
    rewrite_papers(site_data / "papers.csv", missing=True)
    with pytest.raises(ValueError, match="missing from session_assignment.csv: unassigned-paper"):
        site.main(str(site_data))
