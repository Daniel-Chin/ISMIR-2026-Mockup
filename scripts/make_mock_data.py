"""Generate a small mock dataset for a 3-hour test conference.

Creates:
  sitedata_mock/   - papers.csv, events.csv, lbds.csv, music.csv, industry.csv,
                     config.yml
  mock_inputs/     - private-shaped fake registration input (never published)
  static/mock/     - placeholder PDFs (paper/poster/slides per paper, LBD, sponsor)
  static/calendar/<config name>.ics

Run from the repo root:
  python scripts/make_mock_data.py

Then preview the site:
  python main.py --mockup

Slack channel names follow the real pipeline (modules/papers.py:title2channelID).
channel_url / live_url columns are left empty: they get filled by
`miniconf_prep.py --action setup-*` (Slack) and `setup-zoom` (Zoom).
"""

import csv
from datetime import date
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def title2channelID(title, session_number, paper_number):
    # Copy of modules/papers.py:title2channelID — importing that module pulls in
    # utils/slack.py, which configures Slack clients at import time.
    prefix = f"p{session_number}-{paper_number}"
    cleaned = title.lstrip().lower()
    cleaned = re.sub(r"[+?._:,]", "", cleaned)
    cleaned = re.sub(r"[&]", "and", cleaned)
    cleaned = re.sub(r"[\s,_]", "-", cleaned)
    return f"{prefix}-" + "-".join(cleaned.split("-")[:3])


MOCK_DIR = os.path.join(ROOT, "sitedata_mock")
MOCK_INPUT_DIR = os.path.join(ROOT, "mock_inputs")
PDF_DIR = os.path.join(ROOT, "static", "mock")

# One afternoon, 3 hours. Times use the conference timezone configured in
# sitedata_mock/config.yml (timezone: <IANA zone>).
CONF_DATE = "2026-08-18"
YT_PLACEHOLDER = "aqz-KE-bpKQ"  # Big Buck Bunny (CC) - stand-in video
DUMMY_EMAILS = "mock.author1@example.com;mock.author2@example.com"
MOCK_TUTORIAL_TITLE = "Mock Tutorial: Building a Reproducible MIR Baseline"


def write_pdf(path, title, subtitle=""):
    """Write a minimal one-page valid PDF with two lines of text."""

    def esc(s):
        return s.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

    stream = (
        "BT /F1 20 Tf 60 740 Td ({t}) Tj ET\n"
        "BT /F1 12 Tf 60 710 Td ({s}) Tj ET\n"
        "BT /F1 10 Tf 60 680 Td (Mock placeholder PDF for the virtual "
        "conference test run.) Tj ET".format(t=esc(title[:80]), s=esc(subtitle[:90]))
    ).encode("latin-1", "replace")

    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length %d >>\nstream\n%s\nendstream" % (len(stream), stream),
    ]

    out = b"%PDF-1.4\n"
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n%s\nendobj\n" % (i, obj)
    xref_pos = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for off in offsets:
        out += b"%010d 00000 n \n" % off
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref_pos,
    )
    with open(path, "wb") as f:
        f.write(out)


def write_csv(name, header, rows):
    path = os.path.join(MOCK_DIR, name)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in header})
    print("wrote", path, f"({len(rows)} rows)")


PAPER_TITLES = [
    "Whale Song Structure Discovery with Self-Supervised Audio Models",
    "Cross-Species Melody Transfer: From Birdsong to Piano",
    "Real-Time Beat Tracking on Edge Devices for Live Performance",
    "A Benchmark for Lyrics-Audio Alignment in Low-Resource Languages",
    "Generative Counterpoint with Constraint-Aware Diffusion",
    "Perceptual Evaluation of Neural Audio Codecs for Music Archiving",
]

SUBJECTS = [
    "MIR tasks -> audio analysis",
    "Knowledge-driven approaches to MIR -> machine learning",
    "MIR tasks -> rhythm and tempo",
    "MIR tasks -> alignment, synchronization, and score following",
    "Generation -> music generation",
    "Evaluation -> perceptual studies",
]


def make_papers():
    header = (
        "uid,title,slack_channel,channel_url,authors_and_affil,"
        "abstract,paper_presentation,"
        "primary_subject,secondary_subject,long_presentation,is_tismir,"
        "SpecialTrack,StudentAuthor,AwardNominee,publish_reviews,"
        "summary_of_updates_post_review,"
        "pdf_name,pdf_n_bytes,raw_pdf_path,"
        "raw_video,video,raw_poster_pdf,raw_thumbnail,raw_slides_pdf,"
        "review1,review2,review3,review4,meta_review"
    ).split(",")
    rows = []
    for i, title in enumerate(PAPER_TITLES, start=1):
        uid = str(i)
        paper_file = f"paper_{uid}.pdf"
        paper_path = os.path.join(PDF_DIR, paper_file)
        poster_path = os.path.join(PDF_DIR, f"poster_{uid}.pdf")
        slides_path = os.path.join(PDF_DIR, f"slides_{uid}.pdf")
        write_pdf(paper_path, title, "Camera-ready paper")
        write_pdf(poster_path, title, "Poster")
        write_pdf(slides_path, title, "Slides")
        rows.append(
            {
                "uid": uid,
                "title": title,
                "slack_channel": title2channelID(title, 1, i),
                "channel_url": "",
                "authors_and_affil": f"Mock Author{i}A (Mock University)*; "
                f"Mock Author{i}B (Test Institute)",
                "abstract": f"This is the mock abstract for paper {uid}: {title}. "
                "It exists only to test the virtual conference pipeline "
                "(website, Slack channels, Zoom links, and embedded media).",
                "paper_presentation": "In-person" if i % 2 else "Virtual",
                "primary_subject": SUBJECTS[i - 1],
                "secondary_subject": SUBJECTS[i % len(SUBJECTS)],
                "long_presentation": "TRUE" if i <= 2 else "FALSE",
                "is_tismir": "FALSE",
                "SpecialTrack": "FALSE",
                "StudentAuthor": "TRUE" if i % 2 else "FALSE",
                "AwardNominee": "A1-1" if i == 1 else "No",
                "publish_reviews": "FALSE",
                "summary_of_updates_post_review": "",
                "pdf_name": paper_file,
                "pdf_n_bytes": str(os.path.getsize(paper_path)),
                "raw_pdf_path": f"static/mock/paper_{uid}.pdf",
                "raw_video": "",
                "video": f"https://www.youtube.com/embed/{YT_PLACEHOLDER}",
                "raw_poster_pdf": f"static/mock/poster_{uid}.pdf",
                "raw_thumbnail": "static/images/ismir_tabicon.png",
                "raw_slides_pdf": f"static/mock/slides_{uid}.pdf",
            }
        )
    write_csv("papers.csv", header, rows)
    with open(os.path.join(MOCK_DIR, "session_assignment.csv"), "w", newline="") as f:
        csv.writer(f).writerows([
            ["Session Name", "Mock posters"],
            ["Session Day & Time", f"{date.fromisoformat(CONF_DATE):%a}, 19:00 - 19:45"],
            ["Preferred Timezone/s", ""],
            ["Session Chair - Onsite", "Mock Chair"],
            ["Session Chair - Remote", ""],
            *[[f"Paper-{i}", row["uid"]] for i, row in enumerate(rows, start=1)],
        ])


def make_events():
    header = (
        "uid,title,day,start_date,start_time,end_time,category,description,"
        "organiser,organiser_emails,organiser_affiliation,organiser_bio,image,"
        "web_link,slack_channel,channel_url,live_url,thumbnail_link,event_desc"
    ).split(",")
    program = [
        ("Opening Session", "18:00", "18:10", "Opening", "Welcome to the mock run."),
        (
            MOCK_TUTORIAL_TITLE,
            "18:10",
            "18:30",
            "Tutorials",
            "A short hands-on rehearsal of tutorial delivery and Slack onboarding.",
        ),
        ("Oral Session - 1", "18:30", "19:00", "Poster session", "Six mock papers."),
        (
            "Poster Session - 1",
            "19:00",
            "19:45",
            "Poster session",
            "Posters + Slack Q&A.",
        ),
        ("LBD Session", "19:45", "20:10", "LBD", "Late-breaking demos."),
        ("Industry Session", "20:10", "20:30", "Industry", "Sponsor talks."),
        ("Music Program", "20:30", "20:50", "Music", "One mock performance."),
        ("Closing & Awards", "20:50", "21:00", "Awards", "Wrap-up."),
    ]
    rows = []
    for i, (title, start, end, cat, desc) in enumerate(program, start=1):
        rows.append(
            {
                "uid": str(i),
                "title": title,
                "day": "1",
                "start_date": CONF_DATE,
                "start_time": start,
                "end_time": end,
                "category": cat,
                "description": desc,
                "organiser": (
                    "Dr. Ada Mock and Prof. Test Signal"
                    if cat == "Tutorials"
                    else "Mock Chairs"
                ),
                "organiser_emails": (DUMMY_EMAILS if cat == "Tutorials" else ""),
                "organiser_affiliation": (
                    "Mock University; Test Institute" if cat == "Tutorials" else ""
                ),
                "organiser_bio": (
                    "The presenters build reproducible MIR evaluation pipelines."
                    if cat == "Tutorials"
                    else ""
                ),
                "web_link": "",
                "slack_channel": (
                    "tutorial-reproducible-mir" if cat == "Tutorials" else ""
                ),
                "channel_url": "",
                "live_url": "",
            }
        )
    # main.py group_by_days iterates days 1-5 and KeyErrors on a missing day;
    # give days 2-5 a filler event.
    year, month, day = (int(x) for x in CONF_DATE.split("-"))
    for d in range(2, 6):
        rows.append(
            {
                "uid": str(len(program) + d - 1),
                "title": "No sessions (mock buffer day)",
                "day": str(d),
                "start_date": f"{year:04d}-{month:02d}-{day + d - 1:02d}",
                "start_time": "9:00",
                "end_time": "9:15",
                "category": "Social",
                "description": "Placeholder so the site renders days 1-5.",
                "web_link": "",
                "channel_url": "",
                "live_url": "",
            }
        )
    write_csv("events.csv", header, rows)


def make_tutorial_registration():
    from modules.tutorials import REGISTRATION_EMAIL, TUTORIAL_FEE_COLUMNS

    header = [REGISTRATION_EMAIL, *TUTORIAL_FEE_COLUMNS]
    rows = [
        {REGISTRATION_EMAIL: "mock.attendee@example.com", **{c: "0" for c in TUTORIAL_FEE_COLUMNS},
         TUTORIAL_FEE_COLUMNS[0]: "1"}
    ]
    path = os.path.join(MOCK_INPUT_DIR, "tutorial_registration.csv")
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=header)
        writer.writeheader()
        writer.writerows(rows)
    print("wrote", path, f"({len(rows)} rows)")


def make_lbds():
    header = (
        "uid,position,title,abstract,primary_author,primary_email,authors,"
        "affiliations,author_emails,paper_link,poster_link,youtube_id,gd_id,"
        "thumbnail_link,primary_subject,secondary_subject,channel_name,"
        "channel_url,session"
    ).split(",")
    titles = [
        "Live Demo: Humming-to-Score Transcription in the Browser",
        "An Open Dataset of Field Recordings with Aligned Annotations",
    ]
    rows = []
    for i, title in enumerate(titles, start=1):
        uid = str(100 + i)
        write_pdf(
            os.path.join(PDF_DIR, f"lbd_{uid}.pdf"), title, "LBD extended abstract"
        )
        rows.append(
            {
                "uid": uid,
                "position": str(i),
                "title": title,
                "abstract": f"Mock LBD {uid}: {title}. Pipeline test only.",
                "primary_author": f"Mock Demoer{i}",
                "primary_email": "mock.author1@example.com",
                "authors": f"Demoer{i}, Mock; Helper{i}, Test",
                "affiliations": f"Mock Demoer{i} (Mock Lab); Test Helper{i} (Test Lab)",
                "author_emails": DUMMY_EMAILS,
                "paper_link": f"static/mock/lbd_{uid}.pdf",
                "poster_link": f"static/mock/lbd_{uid}.pdf",
                "youtube_id": YT_PLACEHOLDER,
                "thumbnail_link": "static/images/ismir_tabicon.png",
                "primary_subject": "Dataset" if i == 2 else "Demo",
                "channel_name": "",
                "channel_url": "",
                "session": "1",
            }
        )
    write_csv("lbds.csv", header, rows)


def make_music():
    # NOTE: format_music in main.py reads a bb_id key that the real 2025 CSV
    # lacks; include it here so the music page renders.
    header = (
        "uid,position,title,abstract,primary_author,primary_email,authors,"
        "author_emails,affiliation,bio,web_link,gd_id,session,yt_id,bb_id,"
        "thumbnail_link,channel_name,channel_url,release_consent"
    ).split(",")
    rows = [
        {
            "uid": "1",
            "position": "1",
            "title": "Mock Performance: Generative Duet for Synth and Birdsong",
            "abstract": "A short mock performance to test the music program page.",
            "primary_author": "Mock Performer",
            "primary_email": "mock.author1@example.com",
            "authors": "Mock Performer",
            "author_emails": DUMMY_EMAILS,
            "affiliation": "Mock Conservatory",
            "bio": "<b>Mock Performer</b> tests virtual conference pipelines.",
            "web_link": "",
            "session": "1",
            "yt_id": YT_PLACEHOLDER,
            "bb_id": "",
            "thumbnail_link": "static/images/ismir_tabicon.png",
            "channel_name": "",
            "channel_url": "",
            "release_consent": "TRUE",
        }
    ]
    write_csv("music.csv", header, rows)


def make_industry():
    header = (
        "uid,company,title,session,rep,registered_emails,abstract,pdf,video,"
        "video2,logo,channel_name,channel_url,external_web_link,"
        "hiring_web_link,type,Complete"
    ).split(",")
    companies = [
        ("mockcorp", "MockCorp", "Platinum"),
        ("testsound", "TestSound", "Gold"),
    ]
    rows = []
    for uid, company, tier in companies:
        write_pdf(
            os.path.join(PDF_DIR, f"sponsor_{uid}.pdf"), company, f"{tier} sponsor deck"
        )
        rows.append(
            {
                "uid": uid,
                "company": company,
                "title": f"{company}: Audio AI in Production",
                "session": tier,
                "rep": "Mock Rep",
                "registered_emails": DUMMY_EMAILS,
                "abstract": f"Mock sponsor slot for {company}.",
                "pdf": f"static/mock/sponsor_{uid}.pdf",
                "video": f"https://www.youtube.com/embed/{YT_PLACEHOLDER}",
                "logo": "static/images/ismir_tabicon.png",
                "channel_name": "",
                "channel_url": "",
                "external_web_link": "https://example.com",
                "type": "sponsor",
                "Complete": "TRUE",
            }
        )
    write_csv("industry.csv", header, rows)


def make_config():
    with open(os.path.join(ROOT, "sitedata", "config.yml")) as f:
        cfg = f.read()
    cfg = (
        cfg.replace("name: ISMIR 2026", "name: ISMIR 2026 Mock Run")
        .replace(
            "tagline: ISMIR 2026 HYBRID CONFERENCE", "tagline: 3-HOUR PIPELINE TEST"
        )
        .replace("citation_date: 2026 (dates TBD)", "citation_date: 18 August 2026")
        .replace("date: 2026 (dates TBD)", "date: 18 August 2026 (mock)")
        .replace("paper_day_release: 3", "paper_day_release: 1")
        .replace("lbd_day_release: 4", "lbd_day_release: 1")
        .replace("prefix: 'ISMIR 2026'", "prefix: 'ISMIR 2026 Mock'")
    )
    path = os.path.join(MOCK_DIR, "config.yml")
    conference_date = date.fromisoformat(CONF_DATE)
    cfg = re.sub(r"^date:.*$", f"date: {conference_date:%Y %b} {conference_date.day}-{conference_date.day}", cfg, flags=re.MULTILINE)
    with open(path, "w") as f:
        f.write(cfg)
    print("wrote", path)


def make_calendar():
    from scripts.calendar_csv2ics import calendar_csv2ics
    from utils.shared import calendar_ics_path

    # Same file main.py's /getCalendar route serves.
    ics_path = os.path.join(ROOT, calendar_ics_path(MOCK_DIR))
    calendar_csv2ics(in_csv=os.path.join(MOCK_DIR, "events.csv"), out_ics=ics_path)
    print("wrote", ics_path)


def main():
    os.makedirs(MOCK_DIR, exist_ok=True)
    os.makedirs(MOCK_INPUT_DIR, exist_ok=True)
    os.makedirs(PDF_DIR, exist_ok=True)
    make_papers()
    make_events()
    make_tutorial_registration()
    make_lbds()
    make_music()
    make_industry()
    make_config()
    make_calendar()
    print("\nDone. Preview with: python main.py --mockup")


if __name__ == "__main__":
    main()
