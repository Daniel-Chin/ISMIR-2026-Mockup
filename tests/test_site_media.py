import csv
from pathlib import Path

import pytest

import main as site


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/watch?v=aqz-KE-bpKQ",
    "https://www.youtube.com/watch?t=30&v=aqz-KE-bpKQ",
    "https://youtu.be/aqz-KE-bpKQ?t=30",
    "https://www.youtube.com/embed/aqz-KE-bpKQ?start=30",
])
def test_youtube_formats(url):
    assert site.get_yt_id(url) == "aqz-KE-bpKQ"


@pytest.mark.parametrize("url", [
    "https://www.youtube.com/embed/short",
    "https://youtu.be/aqz-KE-bpKQextra",
    "https://example.org/watch?v=aqz-KE-bpKQ",
    "https://www.youtube.com/watch",
])
def test_invalid_youtube_url(url):
    with pytest.raises(ValueError, match="Invalid YouTube URL"):
        site.get_yt_id(url)


def test_empty_youtube_url():
    assert site.get_yt_id("") == ""


@pytest.mark.parametrize("value", [None, ""])  # Outdated: "   ", "https://youtu.be/aqz-KE-bpKQ"
def test_optional_paper_video(value):
    path = Path(__file__).resolve().parents[1] / "sitedata" / "papers.csv"
    with path.open() as handle:
        paper = next(csv.DictReader(handle))
    paper.update(session="1", position="1", day="1")
    paper.pop("video", None)
    assert site.format_paper(paper)["content"]["video"] == ""
    paper["video"] = value
    assert site.format_paper(paper)["content"]["video"] == (value or "").strip()


def test_industry_render_preserves_source_urls(monkeypatch):
    paper = {"video": "https://www.youtube.com/embed/aqz-KE-bpKQ", "video2": ""}
    monkeypatch.setattr(site, "by_uid", {"industry": {"test": paper}})
    monkeypatch.setattr(site, "_data", lambda: {})
    monkeypatch.setattr(site, "render_template", lambda template, **data: data)
    for _ in range(2):
        assert site.industry("test")["industry"]["video"] == "aqz-KE-bpKQ"
    assert paper["video"] == "https://www.youtube.com/embed/aqz-KE-bpKQ"
