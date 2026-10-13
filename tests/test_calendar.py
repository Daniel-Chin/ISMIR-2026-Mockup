from datetime import datetime, timedelta

import pytest

from utils.calendar import build_calendar


@pytest.mark.parametrize("end_time", ["0:15", "tbd"])
def test_calendar_handles_month_boundary_and_unknown_end(end_time):
    events = [{
        "title": "Poster Session - 2",
        "category": "Poster session",
        "start_date": "2026-11-30",
        "start_time": "23:30",
        "end_time": end_time,
    }]
    schedule, = build_calendar(events, {
        "timezone": "Asia/Dubai",
        "miniconf_url": "https://example.com/conference",
    })
    start = datetime.fromisoformat(schedule["start"])
    end = datetime.fromisoformat(schedule["end"])
    assert start.isoformat() == "2026-11-30T19:30:00+00:00"
    assert end - start == timedelta(minutes=45 if end_time == "0:15" else 180)
    assert schedule["location"] == "papers.html?session=2&type=poster"
    assert schedule["calendarId"] == "pos"
    assert schedule["raw"]["endTimeTbd"] is (end_time == "tbd")
    assert schedule["scrollKey"] == (
        "Miniconf page: https://example.com/conference/papers.html?session=2&type=poster"
    )


def test_calendar_uses_selected_csv_without_precomputed_json(tmp_path, monkeypatch):
    import main

    monkeypatch.setattr(main, "site_data", {})
    monkeypatch.setattr(main, "by_uid", {})
    monkeypatch.setattr(main, "load_dotenv", lambda: None)
    monkeypatch.setenv("ZOOM_REDIRECT_ACCESS_TOKEN", "test-token")
    for name in ("papers", "industry", "music", "lbds"):
        (tmp_path / f"{name}.csv").write_text("uid\n")
    (tmp_path / "events.csv").write_text(
        "uid,title,day,start_date,start_time,end_time,category\n"
        + "".join(
            f"{day},CSV event,{day},2026-09-24,9:00,10:00,Opening\n"
            for day in range(1, 6)
        )
    )
    (tmp_path / "config.yml").write_text("timezone: Asia/Dubai\n")
    (tmp_path / "main_calendar.json").write_text("invalid obsolete JSON")

    main.main(str(tmp_path))
    response = main.app.test_client().get("/serve_main_calendar.json")
    assert response.status_code == 200
    assert response.get_json()[0]["title"] == "CSV event"
    assert response.get_json()[0]["start"] == "2026-09-24T05:00:00+00:00"
    assert ("serve", {"path": "main_calendar"}) in list(main.generator())
