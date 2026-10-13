'''
uv run python -m utils.session_assignment
'''
import os
import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from functools import lru_cache
import itertools
from zoneinfo import ZoneInfo
from pprint import pprint

from utils.shared import load_conference_timezone, load_site_config, format_session_window, parse_conference_dates

@dataclass(frozen=True)
class Session:
    index: int  # starts from 1
    name: str   # internal, do not display
    start_time: datetime
    end_time: datetime
    chair_onsite: str
    chair_remote: str
    papers: list[str]   # uid. list order agrees with Paper.position

    day: int            # starts from 1; derived

@dataclass(frozen=True)
class Paper:
    uid: str
    session_index: int  # starts from 1
    position: int       # starts from 1

    day: int            # starts from 1; derived

@lru_cache(maxsize=4)
def parse_file(sitedata_path: str) -> tuple[list[Session], list[Paper]]:
    conf_config = load_site_config(sitedata_path)
    zone_info = load_conference_timezone(sitedata_path)
    csv_path = os.path.join(sitedata_path, 'session_assignment.csv')
    with open(csv_path, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        row = next(reader)
        assert row[0] == 'Session Name'
        names = row[1:]
        row = next(reader)
        assert row[0].startswith('Session Day & Time')
        time_blocks = row[1:]
        _ = next(reader)
        row = next(reader)
        assert row[0] == 'Session Chair - Onsite'
        chairs_onsite = row[1:]
        row = next(reader)
        assert row[0] == 'Session Chair - Remote'
        chairs_remote = row[1:]

        paper_matrix = list[list[str]]()  # papers[position - 1][session_index - 1]
        for position, row in zip(itertools.count(1), reader):
            assert row[0] == f'Paper-{position}'
            paper_matrix.append([*row[1:]])

    sessions = list[Session]()
    # Day 1 is the conference start date, matching events.csv.
    first_date = parse_conference_start(conf_config, zone_info).date()
    for i, name in enumerate(names):
        start_time, end_time = parse_time_block(
            conf_config, zone_info, time_blocks[i],
        )
        day = ((
            start_time.astimezone(zone_info).date() - first_date
        ).days + 1)
        sessions.append(
            Session(
                index=i + 1,
                name=name,
                start_time=start_time,
                end_time=end_time,
                chair_onsite=chairs_onsite[i],
                chair_remote=chairs_remote[i],
                papers=[
                    paper_row[i] for paper_row in paper_matrix
                ],
                day=day,
            )
        )

    papers = list[Paper]()
    for session in sessions:
        for position, paper_uid in enumerate(session.papers, start=1):
            papers.append(
                Paper(
                    uid=paper_uid,
                    session_index=session.index,
                    position=position,
                    day=session.day,
                )
            )

    return sessions, papers


def parse_conference_start(conf_config: dict, zone_info: ZoneInfo) -> datetime:
    first_date, _ = parse_conference_dates(conf_config)
    return datetime(first_date.year, first_date.month, first_date.day, tzinfo=zone_info)


def parse_time_block(
    conf_config: dict,
    zone_info: ZoneInfo,
    time_block: str,
) -> tuple[datetime, datetime]:
    '''
    Example input: "Mon, 10:00 - 11:30"
    '''
    conference_start = parse_conference_start(conf_config, zone_info)

    weekday_name, time_window = time_block.split(', ')
    weekday_map = {
        'Mon': 0,
        'Tue': 1,
        'Wed': 2,
        'Thu': 3,
        'Fri': 4,
        'Sat': 5,
        'Sun': 6,
    }
    target_weekday = weekday_map[weekday_name]

    current_date = conference_start.date()
    while current_date.weekday() != target_weekday:
        current_date += timedelta(days=1)

    start_literal, end_literal = time_window.split(' - ')
    start_time = datetime.strptime(start_literal, '%H:%M').time()  # noqa: DTZ007
    end_time   = datetime.strptime(  end_literal, '%H:%M').time()  # noqa: DTZ007

    start_datetime = datetime(
        current_date.year,
        current_date.month,
        current_date.day,
        start_time.hour,
        start_time.minute,
        tzinfo=zone_info,
    )
    end_datetime = datetime(
        current_date.year,
        current_date.month,
        current_date.day,
        end_time.hour,
        end_time.minute,
        tzinfo=zone_info,
    )
    return start_datetime, end_datetime

def debug():
    sessions, papers = parse_file('./sitedata/')
    for x in [*sessions, *papers]:
        pprint(x)
        input('Enter...')

def export_paper_view(sitedata_path: str):
    HEADER = [
        'uid',
        'title',
        'day',
        'session_index',
        'time_block',
        'chair_onsite',
        'chair_remote',
        'position_in_session',
    ]

    zone_info = load_conference_timezone(sitedata_path)
    sessions, papers = parse_file(sitedata_path)
    paper_title = dict[str, str]()
    with open(os.path.join(
        sitedata_path, 'papers.csv', 
    ), 'r', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        for row in reader:
            paper_title[row['uid']] = row['title']
    out_path = os.path.join(
        sitedata_path, 'session_assignment-by_paper.csv', 
    )
    with open(out_path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        def write_message(msg: str):
            buf = ['' for _ in HEADER]
            buf[0] = msg
            writer.writerow(buf)
        write_message('README')    
        write_message('This tab is read-only. Do not edit anything.')
        write_message("It's generated from the session assignment matrix. That sheet is the source and is editable. This sheet is just a by-paper view for convenience.")
        write_message("It's NOT used to update ANYTHING (website, slack).")
        write_message('')
        dict_writer = csv.DictWriter(f, fieldnames=HEADER)
        dict_writer.writeheader()
        for paper in papers:
            session = sessions[paper.session_index - 1]
            dict_writer.writerow({
                'uid': paper.uid,
                'title': paper_title[paper.uid],
                'day': paper.day,
                'session_index': paper.session_index,
                'time_block': format_session_window(
                    session.start_time,
                    session.end_time,
                    zone_info, 
                ),
                'chair_onsite': session.chair_onsite,
                'chair_remote': session.chair_remote,
                'position_in_session': paper.position,
            })
    print('CSV written to below file. Hint: Copy content and paste to Google Sheets?')
    print(out_path)

if __name__ == "__main__":
    # debug()
    export_paper_view('./sitedata/')
