"""Fix the poster screens' plans in lbd_schedule.json, against the video screens' default plans.

Run on an organizer's machine, after any change to the video plans or the LBDs, then commit the result:
    python3 onsite-kit/plan_posters.py
Every MacBook then shows the same posters at the same times, none while its own video or cover is on.
"""

import json
import sys
import tempfile
from pathlib import Path

import serve


def main():
    # Plan against the default video plans and the YouTube lengths, not this machine's saved state.
    serve.STATE = Path(tempfile.mkdtemp())
    serve.PROBES = serve.STATE / 'probes.json'
    path = serve.KIT / 'lbd_schedule.json'
    plan = json.loads(path.read_text(encoding='utf-8'))
    plan.pop('posters', None)
    path.write_text(json.dumps(plan, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    kit = serve.Kit()
    if not kit.poster_order:
        sys.exit('No LBDs in .onsite_env: run make_env.py first')
    plan['posters'] = {screen: kit.plan_posters(screen) for screen in serve.POSTER_SCREENS}
    path.write_text(json.dumps(plan, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    kit = serve.Kit()
    clashes = kit.conflicts()
    for screen, poster_plan in plan['posters'].items():
        print(f'{screen}: {len(poster_plan["plays"])} posters, {poster_plan["poster_s"]} s each')
    print(f'{len(clashes)} clashes with the video screens' + (f': {clashes}' if clashes else ''))
    sys.exit(1 if clashes else 0)


if __name__ == '__main__':
    main()
