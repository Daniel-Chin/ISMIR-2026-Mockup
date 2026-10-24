'''
Reports papers whose presenter (oral_session_presenter in papers.csv) has not registered.
uv run python -m scripts.less_generalizable.presenter_registration
'''
import argparse
import csv
from pathlib import Path

from utils.identity import (
    Person, Registrant, ambiguous_tokens, load_cmt_authors, load_registrants, match_evidence, names_match,
    share_name_token,
)

STRONG_EVIDENCE = ('email', 'name')
ROOT = Path(__file__).resolve().parents[2]


def resolve_presenter(presenter: str, authors: list[tuple[str, str]]) -> tuple[Person, bool]:
    """Joins the presenter with their CMT record(s) on the paper; False if no author's name resembles theirs."""
    ambiguous = ambiguous_tokens(n for n, _ in authors)
    hits = ([a for a in authors if names_match(presenter, a[0])]
            or [a for a in authors if share_name_token(presenter, a[0], ambiguous)])
    return Person.of([presenter, *(n for n, _ in hits)], [e for _, e in hits]), bool(hits)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--registration', type=Path, default=ROOT / 'local/registration/Registrant Details - latest.csv')
    parser.add_argument('--cmt', type=Path, default=ROOT / 'local/cmt_authors.csv')
    parser.add_argument('--sitedata', type=Path, default=ROOT / 'sitedata')
    args = parser.parse_args()

    with (args.sitedata / 'papers.csv').open(newline='', encoding='utf-8') as f:
        papers = list(csv.DictReader(f))
    cmt = load_cmt_authors(args.cmt)
    registrants = load_registrants(args.registration)

    def registrations(person: Person, uid: str) -> list[tuple[Registrant, str]]:
        ambiguous = ambiguous_tokens(n for n, _ in cmt.get(uid, []))
        return [(r, evidence) for r in registrants
                if (evidence := match_evidence(person, r.person, uid in r.claimed_papers, ambiguous))]

    def registered_authors(uid: str) -> list[str]:
        return [name for name, email in cmt.get(uid, []) if registrations(Person.of([name], [email]), uid)]

    marked = missing = 0
    missing_lines, weak_lines, unresolved_lines, due_lines, unmarked_lines = [], [], [], [], []
    for paper in papers:
        uid, presenter = paper['uid'], paper['oral_session_presenter'].strip()
        if uid not in cmt:
            print(f'Warning: paper {uid} is not in the CMT export')
        if not presenter:
            unmarked_lines.append(f'  {uid:>4}  registered authors: {", ".join(registered_authors(uid)) or "-"}')
            continue
        marked += 1
        person, resolved = resolve_presenter(presenter, cmt.get(uid, []))
        if not resolved:
            unresolved_lines.append(f'  {uid:>4}  {presenter}')
        hits = registrations(person, uid)
        if not hits:
            missing += 1
            claimants = [r.name for r in registrants if uid in r.claimed_papers]
            missing_lines.append(f'  {uid:>4}  {presenter:<28} claimed by: {"; ".join(claimants) or "-"}'
                                 f' | registered authors: {", ".join(registered_authors(uid)) or "-"}')
            continue
        if strong := [(r, evidence) for r, evidence in hits if evidence in STRONG_EVIDENCE]:
            hits = strong
        else:
            weak_lines += [f'  {uid:>4}  {presenter:<28} <- {r.name} ({evidence})' for r, evidence in hits]
        due_lines += [f'  {uid:>4}  {presenter:<28} {r.amount_due:g}' for r, _ in hits if r.amount_due > 0]

    missing_uids = [line.split()[0] for line in missing_lines]
    print(f'Presenters registered: {marked - missing}/{marked} ({(marked - missing) / marked:.1%})')
    print(f'Missing ({missing}): {", ".join(missing_uids)}')
    print('\n'.join(missing_lines))
    for title, lines in [
        ('Registered by weak evidence only; check', weak_lines),
        ("Presenter not found among the paper's CMT authors", unresolved_lines),
        ('Registered presenters with an amount due', due_lines),
        ('No presenter marked', unmarked_lines),
    ]:
        if lines:
            print(f'\n{title} ({len(lines)}):')
            print('\n'.join(lines))


if __name__ == '__main__':
    main()
