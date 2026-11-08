"""llm_files.build: the plain-text programme the copied LLM prompts link to."""
import re
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import llm_files  # noqa: E402

CONF = {'name': 'ISMIR 2026', 'date': '2026 Nov 8-12', 'timezone': 'Asia/Dubai', 'miniconf_url': 'https://program.example',
        'helpdesk_url': 'https://slack.example/help', 'official_site_url': ''}


def paper(uid, n, i, **extra):
    return {'id': f'paper-{uid}', 'sourcePaperId': uid, 'displayId': f'P{n}-0{i}', 'title': f'Paper {uid}', 'authors': 'A; B',
            'subjects': ['Topic -> leaf one', 'Topic'], 'presenterMode': 'online', 'abstract': f'Abstract {uid}.',
            'detailUrl': f'https://program.example/poster_{uid}.html', 'links': {'slack': f'https://slack.example/{uid}'}, **extra}


def event(eid, kind, start, end, **extra):
    return {'id': f'event-{eid}', 'sourceEventId': str(eid), 'title': f'{kind} {eid}', 'type': kind, 'category': kind,
            'startsAt': f'2026-11-09T{start}:00+04:00', 'endsAt': f'2026-11-09T{end}:00+04:00', **extra}


SCHEDULE = {'conference': {'timeZone': 'Asia/Dubai'}, 'events': [
    event(1, 'oral', '10:00', '10:30', sessionNumber=1, links={'zoom': 'https://zoom.us/j/1?pwd=secret', 'slack': 'https://slack.example/o1', 'youtube': 'Confidential'},
          papers=[paper('7', 1, 1, funFact='NA'), paper('9', 1, 2)]),
    event(2, 'poster', '10:30', '11:30', sessionNumber=1, links={'zoom': 'https://zoom.us/j/2'}, papers=[paper('7', 1, 1), paper('9', 1, 2)]),
    event(3, 'keynote', '12:00', '13:00', links={'youtube': 'https://youtube.example/live'}, summary='  A   talk. '),
    event(4, 'special', '13:00', '14:00', debugOnly=True),
]}


class LlmFilesTest(unittest.TestCase):
    def setUp(self):
        self.files = llm_files.build(SCHEDULE, CONF)

    def test_files_and_cross_links(self):
        self.assertEqual(sorted(self.files), ['index.txt', 'papers.txt', 'session-1.txt'])
        base = 'https://program.example/live_overview/llm/'
        for text in self.files.values():
            for name in re.findall(re.escape(base) + r'([\w.-]+\.txt)', text):
                if name != 'session-N.txt':
                    self.assertIn(name, self.files)

    def test_no_secret_links_or_placeholders(self):
        everything = '\n'.join(self.files.values())
        self.assertNotIn('zoom.us', everything)
        self.assertNotIn('Confidential', everything)
        self.assertNotIn('Fun fact: NA', everything)
        self.assertIn('Zoom: https://program.example/zoom.html?event_uid=1', everything)
        self.assertIn('Livestream: https://youtube.example/live', everything)

    def test_content(self):
        index, papers, session = self.files['index.txt'], self.files['papers.txt'], self.files['session-1.txt']
        self.assertIn('Asia/Dubai (UTC+04:00)', index)
        self.assertIn('- 12:00–13:00 keynote 3 (keynote) · A talk.', index)
        self.assertNotIn('special 4', index)   # debug-only events stay off
        self.assertEqual(papers.count('P1-01'), 1)   # oral and poster share papers
        self.assertIn('P1-01 "Paper 7" — A; B · leaf one; Topic', papers)
        self.assertEqual(session.count('## P1-01 Paper 7'), 1)
        self.assertIn('Abstract: Abstract 7.', session)
        self.assertIn('presented virtual', session)


if __name__ == '__main__':
    unittest.main()
