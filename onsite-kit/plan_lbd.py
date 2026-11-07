"""Write the LBD plan the Live Database asks for into lbd_schedule.json, the repo's reference plan.

Each MacBook works the plan out itself (LBD screens -> Update from the Live Database), so this is needed only
to start new MacBooks from the current plan; commit the result. Run where the videos are downloaded:
    python3 onsite-kit/plan_lbd.py
"""

import json
import sys
import tempfile
from pathlib import Path

import serve


def main():
    serve.STATE = Path(tempfile.mkdtemp())  # not this machine's own plan or edits
    serve.PROBES = serve.STATE / 'probes.json'
    kit = serve.Kit()
    kit.read_live()
    plan, problems = kit.new_plan()
    for line in serve.lbdplan.changes(kit.reference, plan) or ['No change.']:
        print(line)
    for problem in problems:
        print('PROBLEM:', problem)
    path = serve.KIT / 'lbd_schedule.json'
    path.write_text(json.dumps(plan, indent=1, ensure_ascii=False) + '\n', encoding='utf-8')
    kit = serve.Kit()
    clashes = kit.conflicts()
    print(f'{len(clashes)} clashes between posters and their videos' + (f': {clashes}' if clashes else ''))
    sys.exit(1 if clashes or problems else 0)


if __name__ == '__main__':
    main()
