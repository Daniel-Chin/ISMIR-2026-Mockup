"""The LBD video and poster screens' plan, worked out from the Live Database. Python standard library only.

Every MacBook works out the same plan from the same sheets and the same video files, so a change in the sheets
reaches every screen without copying anything: see "LBD plan" in README.md. lbd_schedule.json (in the repo)
is the reference: the screens' names, the YouTube lengths, and which LBDs were planned before.
"""

from __future__ import annotations

import struct
from pathlib import Path

POSTER_SCREENS = [f'P{n}' for n in range(1, 5)]  # screens of posters only, alongside the video screens
CLEAR_MS = 30_000  # a poster keeps this far from its own video, as measured lengths differ a little from YouTube's
ALWAYS_VIDEO = {'m1'}  # the MIREX overview: on the video screen, whatever the sheet says
NO_POSTER_SCREEN = {'m1'}  # ... and on the video screen only
MAX_COVER_S = 20  # the cover before each video takes what the slot leaves, up to this
MIN_COVER_S = 10  # a screen is full when its covers would be shorter than this


def can_present(lbd: dict) -> bool:
    """Shown on the screens: presented online, and cleared to present (ok_to_present not No)."""
    return lbd.get('mode', '').lower() == 'virtual' and lbd.get('ok', 'Yes').strip().lower() != 'no'


def on_video(lbd: dict) -> bool:
    return lbd['uid'] in ALWAYS_VIDEO or can_present(lbd)


def on_poster(lbd: dict) -> bool:
    return lbd['uid'] not in NO_POSTER_SCREEN and can_present(lbd)


def order(uid: str):
    """LBDs by number, then MIREX by number: 569 ... 689, m1 ... m12."""
    number = uid.lstrip('m')
    return uid.startswith('m'), int(number) if number.isdigit() else 0, uid


def mp4_seconds(path: Path):
    """The length an MP4 or MOV file states (moov/mvhd), or None."""
    try:
        with open(path, 'rb') as stream:
            end = path.stat().st_size

            def boxes(start, stop):
                position = start
                while position + 8 <= stop:
                    stream.seek(position)
                    size, kind = struct.unpack('>I4s', stream.read(8))
                    header = 8
                    if size == 1:
                        size, header = struct.unpack('>Q', stream.read(8))[0], 16
                    elif size == 0:
                        size = stop - position
                    if size < header:
                        return
                    yield kind, position + header, position + size
                    position += size

            for kind, start, stop in boxes(0, end):
                if kind == b'moov':
                    for inner, body, _ in boxes(start, stop):
                        if inner == b'mvhd':
                            stream.seek(body)
                            version = stream.read(1)[0]
                            stream.read(3)
                            if version == 1:
                                _, _, scale, length = struct.unpack('>QQIQ', stream.read(28))
                            else:
                                _, _, scale, length = struct.unpack('>IIII', stream.read(16))
                            return round(length / scale, 3) if scale else None
    except (OSError, struct.error, IndexError):
        return None
    return None


def arrange(uids: list, free) -> list:
    """uids ordered so each sits at a place where free(uid, place), as near its own place as can be.

    A matching of papers to places, by augmenting paths; a paper with no free place left takes an empty one.
    """
    holder: list = [None] * len(uids)

    def place(index, tried):
        for spot in sorted(range(len(uids)), key=lambda spot: abs(spot - index)):
            if spot not in tried and free(uids[index], spot):
                tried.add(spot)
                if holder[spot] is None or place(holder[spot], tried):
                    holder[spot] = index
                    return True
        return False

    stuck = [index for index in range(len(uids)) if not place(index, set())]
    for spot in range(len(uids)):
        if holder[spot] is None:
            holder[spot] = stuck.pop(0)
    return [uids[index] for index in holder]


def video_runs(screens: dict, seconds: dict, start_ms: int) -> dict:
    """uid -> the times its cover and video are on a video screen."""
    times: dict = {}
    for body in screens.values():
        cursor = start_ms
        for uid in body['plays']:
            length = (body['timetable_s'] + body['poster_s'] + seconds.get(uid, 0)) * 1000
            times.setdefault(uid, []).append((cursor, cursor + length))
            cursor += length
    return times


def plan_posters(uids: list, on_video_ms: dict, start_ms: int, slot_s: int) -> dict:
    """The posters in consecutive runs of the same length, one per poster screen, every poster for the same
    time, each run reordered so that no poster is up while its own video or cover is on."""
    per_screen = -(-len(uids) // len(POSTER_SCREENS))
    poster_s = slot_s // max(per_screen, 1)
    found = {}
    for index, screen in enumerate(POSTER_SCREENS):
        def free(uid, place):
            begin = start_ms + place * poster_s * 1000
            finish = begin + poster_s * 1000
            return not any(begin - CLEAR_MS < end and start < finish + CLEAR_MS for start, end in on_video_ms.get(uid, []))

        found[screen] = {'plays': arrange(uids[index * per_screen:(index + 1) * per_screen], free), 'poster_s': poster_s}
    return found


def build(reference: dict, lbds: list, groups: dict, length_of, start_ms: int, slot_s: int) -> tuple:
    """The plan for these LBDs, and what could not be worked out (videos of unknown length).

    Each LBD plays on the screen of its group (MIREX on the last screen), twice (MIREX three times), in rounds of
    uid order. Where a screen cannot hold them all with covers of MIN_COVER_S, the extra plays move to the end of
    the screen with the most time to spare: first those the reference plan did not play in full on that screen
    (new LBDs, or ones it had split already), then those of the longest videos.
    """
    screens_ref = reference.get('screens', {})
    seconds, problems = {}, []
    wanted = {}  # screen -> {uid: plays}
    for lbd in sorted(lbds, key=lambda lbd: order(lbd['uid'])):
        if not on_video(lbd):
            continue
        uid = lbd['uid']
        screen = str(lbd.get('group') or '')
        if screen not in screens_ref:
            problems.append(f'{uid}: group {screen or "(none)"} has no video screen')
            continue
        length = length_of(uid)
        if not length:
            problems.append(f'{uid}: video length unknown (not downloaded?)')
            continue
        seconds[uid] = length
        wanted.setdefault(screen, {})[uid] = 3 if uid.startswith('m') else 2

    def need(screen_plays):
        return sum(seconds[uid] + MIN_COVER_S for uid in screen_plays)

    guests = []  # extra plays that do not fit at home
    for screen, counts in wanted.items():
        # First the LBDs the reference did not play in full here (new, or already split), so the plan stays put.
        at_home = screens_ref[screen]['plays']
        movable = sorted(counts, key=lambda uid: (at_home.count(uid) >= counts[uid], -seconds[uid], order(uid)))
        while need([uid for uid, n in counts.items() for _ in range(n)]) > slot_s:
            uid = next((uid for uid in movable if counts[uid] > 1), None)
            if uid is None:
                problems.append(f'screen {screen}: too long even with each video once')
                break
            counts[uid] -= 1
            guests.append(uid)

    plays = {screen: [] for screen in screens_ref}
    for screen, counts in wanted.items():
        for round_number in range(1, max(counts.values(), default=0) + 1):
            plays[screen] += [uid for uid in sorted(counts, key=order) if counts[uid] >= round_number]
    for uid in sorted(guests, key=order):
        home = next(screen for screen, counts in wanted.items() if uid in counts)
        spare = {screen: slot_s - need(screen_plays) for screen, screen_plays in plays.items() if screen != home}
        target = max(spare, key=lambda screen: (spare[screen], screen))
        if spare[target] < seconds[uid] + MIN_COVER_S:
            problems.append(f'{uid}: no screen has time for its second play')
            continue
        plays[target].append(uid)

    screens = {}
    for screen, body in screens_ref.items():
        screen_plays = plays.get(screen, [])
        video = sum(seconds[uid] for uid in screen_plays)
        cover = max(0, min(MAX_COVER_S, int((slot_s - video) // len(screen_plays)))) if screen_plays else MAX_COVER_S
        screens[screen] = {'name': body['name'], 'theme': groups.get(screen, body.get('theme', '')), 'poster_s': 0,
                           'timetable_s': cover, 'plays': screen_plays}
    posters = [lbd['uid'] for lbd in sorted(lbds, key=lambda lbd: (int(lbd.get('group') or 99), order(lbd['uid'])))
               if on_poster(lbd)]
    plan = {'note': reference.get('note', ''), 'screens': screens,
            'video_s': {**reference.get('video_s', {}), **seconds},
            'posters': plan_posters(posters, video_runs(screens, seconds, start_ms), start_ms, slot_s)}
    return plan, problems


def changes(old: dict, new: dict) -> list:
    """What a new plan changes, screen by screen, in words."""
    found = []
    for screen, body in new['screens'].items():
        before = old.get('screens', {}).get(screen, {'plays': [], 'timetable_s': None})
        added = sorted(set(body['plays']) - set(before['plays']), key=order)
        removed = sorted(set(before['plays']) - set(body['plays']), key=order)
        counted = sorted((uid for uid in set(body['plays']) & set(before['plays'])
                          if body['plays'].count(uid) != before['plays'].count(uid)), key=order)
        times = ', '.join(f'{uid} ×{body["plays"].count(uid)}' for uid in counted)  # no nested quotes: Python 3.9
        parts = ([f'adds {", ".join(added)}'] if added else []) + ([f'drops {", ".join(removed)}'] if removed else []) \
            + ([f'plays {times}'] if counted else [])
        if parts or body['plays'] != before['plays'] or body['timetable_s'] != before['timetable_s']:
            found.append(f'Screen {screen}: ' + ('; '.join(parts) or 'new order')
                         + f'; cover {body["timetable_s"]} s')
    for screen, body in new.get('posters', {}).items():
        before = old.get('posters', {}).get(screen, {'plays': [], 'poster_s': None})
        if body != before:
            found.append(f'Poster screen {screen}: {len(before["plays"])} -> {len(body["plays"])} posters, '
                         f'{body["poster_s"]} s each')
    return found
