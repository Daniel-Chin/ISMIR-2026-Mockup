'''
Deciding whether records from different sources (CMT, the registration export, Slack) are the same person.
The rules are name-agnostic and err towards false positives: a wrong match costs less than a missed one.
'''
import csv
import functools
import itertools
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

try:
    from local import identity_local as _local  # local/ is gitignored: ALIASES, PAPER_NUMBER_HEADERS
except ImportError:
    _local = None

# Letters that NFKD does not decompose into ASCII
_FOLD = str.maketrans({'ı': 'i', 'ł': 'l', 'ø': 'o', 'đ': 'd', 'ð': 'd', 'þ': 'th', 'ß': 'ss', 'æ': 'ae', 'œ': 'oe'})
_HONORIFICS = {'dr', 'prof', 'mr', 'mrs', 'ms', 'phd'}
_MAX_PERMUTED_TOKENS = 6


@functools.cache
def name_tokens(name: str) -> tuple[str, ...]:
    """'Lee-Ørsted, Dr. Zoë A.' -> ('lee', 'orsted', 'zoe', 'a')"""
    folded = unicodedata.normalize('NFKD', name.lower().translate(_FOLD)).encode('ascii', 'ignore').decode()
    return tuple(t for t in re.findall(r'[a-z]+', folded) if t not in _HONORIFICS)


@functools.cache
def _concatenations(tokens: tuple[str, ...]) -> frozenset[str]:
    if len(tokens) > _MAX_PERMUTED_TOKENS:
        return frozenset({''.join(tokens)})
    return frozenset(''.join(p) for p in itertools.permutations(tokens))


def _is_initial_of(a: str, b: str) -> bool:
    return (len(a) == 1 and b.startswith(a)) or (len(b) == 1 and a.startswith(b))


@functools.cache
def _edit_distance(a: str, b: str) -> int:
    """Optimal string alignment distance: insertions, deletions, substitutions and adjacent swaps."""
    d = [[i + j if i * j == 0 else 0 for j in range(len(b) + 1)] for i in range(len(a) + 1)]
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[-1][-1]


@functools.cache
def _variants(a: str, b: str) -> bool:
    """Spelling variants of one name word: short forms ('Chris' ~ 'Christopher') and one-letter typos or
    transliterations ('Mueller' ~ 'Muller', 'Munroe' ~ 'Murnoe')."""
    if min(len(a), len(b)) >= 3 and (a.startswith(b) or b.startswith(a)):
        return True
    return min(len(a), len(b)) >= 5 and _edit_distance(a, b) <= 1


@functools.cache
def names_match(a: str, b: str, variants: bool = False) -> bool:
    """
    Name-only evidence. Tolerates reordering, hyphens and spacing within names ('Zoe-Ann' = 'ZoeAnn'),
    initials ('Z. Lee' = 'Zoe Lee'), and dropped middle names or extra surnames ('Zoe Lee' = 'Zoe Ann Lee Park').
    variants: words may also be spelling variants of each other, see _variants.
    """
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return False
    if _concatenations(ta) & _concatenations(tb):
        return True
    short, long = sorted((ta, tb), key=len)
    if len(short) < 2:
        return False
    rest = list(long)
    unmatched = []
    for t in short:
        if t in rest:
            rest.remove(t)
        else:
            unmatched.append(t)
    if len(unmatched) == len(short):
        return False
    if variants:
        for t in list(unmatched):
            if hit := next((r for r in rest if len(t) > 1 and _variants(t, r)), None):
                rest.remove(hit)
                unmatched.remove(t)
    for t in unmatched:
        hit = next((r for r in rest if _is_initial_of(t, r)), None)
        if hit is None:
            return False
        rest.remove(hit)
    return True


def ambiguous_tokens(names: Iterable[str]) -> frozenset[str]:
    """Tokens in two or more names of known-distinct people, e.g. co-authors 'Ann Lee' and 'Bo Lee' -> {'lee'}."""
    counts = Counter(t for name in names for t in set(name_tokens(name)))
    return frozenset(t for t, n in counts.items() if n > 1)


@functools.cache
def share_name_token(a: str, b: str, ambiguous: frozenset[str] = frozenset()) -> bool:
    """Weak evidence: the names share a token longer than an initial, other than an ambiguous one."""
    return bool({t for t in name_tokens(a) if len(t) > 1} & set(name_tokens(b)) - ambiguous)


@functools.cache
def normalize_email(email: str) -> str:
    """Drops '+tag' and, for Gmail, dots, since mail to those variants reaches the same inbox."""
    local, _, domain = email.strip().lower().partition('@')
    local = local.split('+', 1)[0]
    if domain in ('gmail.com', 'googlemail.com'):
        local, domain = local.replace('.', ''), 'gmail.com'
    return f'{local}@{domain}'


def _email_handle(email: str) -> str:
    return re.sub(r'[^a-z]', '', email.partition('@')[0])


@functools.cache
def similar_emails(a: str, b: str) -> bool:
    """Weak evidence: one handle at two providers ('zlee@uni.example' ~ 'zlee@home.example'),
    or a one-letter typo or swap at one provider. Expects normalize_email applied."""
    (la, _, da), (lb, _, db) = a.partition('@'), b.partition('@')
    if la == lb:
        return len(_email_handle(a)) >= 5
    return da == db and min(len(la), len(lb)) >= 5 and _edit_distance(la, lb) <= 1


@functools.cache
def email_from_name(email: str, name: str) -> bool:
    """
    Weak evidence: the email handle, ignoring digits and punctuation, is the starts of two or more name words
    in some order, including one whole word of at least 3 letters and at most one initial
    ('zlee99@' or 'zoe.le@' for 'Zoe Lee', but not 'zle@' or 'zalee@' for 'Zoe Ann Lee').
    """
    handle, tokens = _email_handle(email), name_tokens(name)

    def build(rest: str, unused: tuple[str, ...], used: int, whole_word: bool, initials: int) -> bool:
        if initials > 1:
            return False
        if not rest:
            return used >= 2 and whole_word
        return any(rest.startswith(t[:n])
                   and build(rest[n:], unused[:i] + unused[i + 1:], used + 1,
                             whole_word or (n == len(t) >= 3), initials + (n == 1))
                   for i, t in enumerate(unused) for n in range(1, len(t) + 1))

    return len(tokens) <= _MAX_PERMUTED_TOKENS and build(handle, tokens, 0, False, 0)


@dataclass(frozen=True)
class Person:
    names: frozenset[str]
    emails: frozenset[str]  # normalize_email applied

    @classmethod
    def of(cls, names: list[str], emails: list[str]) -> 'Person':
        names = [n for n in names if n.strip()]
        aliases = [a for group in (_local.ALIASES if _local else []) if any(names_match(n, g) for n in names for g in group) for a in group]
        return cls(frozenset(names + aliases), frozenset(normalize_email(e) for e in emails if e.strip()))


@functools.cache
def match_evidence(a: Person, b: Person, related: bool = False, ambiguous: frozenset[str] = frozenset()) -> str | None:
    """
    Why a and b look like the same person, or None. Evidence other than 'email' and 'name' is weak:
    callers that cannot afford false positives should ignore it.
    related: an independent link exists (e.g. both are tied to the same paper), so a partial name suffices.
    ambiguous: tokens that don't count as a partial name, see ambiguous_tokens.
    """
    if a.emails & b.emails:
        return 'email'
    if any(names_match(x, y) for x in a.names for y in b.names):
        return 'name'
    if related and any(share_name_token(x, y, ambiguous) for x in a.names for y in b.names):
        return 'related + partial name'
    if any(names_match(x, y, variants=True) for x in a.names for y in b.names):
        return 'name variant'
    if any(email_from_name(e, n) for e, n in [*itertools.product(a.emails, b.names), *itertools.product(b.emails, a.names)]):
        return 'email resembles name'
    if any(similar_emails(x, y) for x in a.emails for y in b.emails):
        return 'similar email'
    return None


def find_person(person: Person, candidates: list[Person]) -> tuple[list[int], bool]:
    """
    Indices of candidates that are person, and whether the match is fuzzy. Strong evidence ('email', 'name')
    may match several candidates; failing that, weak evidence counts only when it matches exactly one.
    """
    evidence = [match_evidence(person, c) for c in candidates]
    strong = [i for i, e in enumerate(evidence) if e in ('email', 'name')]
    if strong:
        return strong, False
    weak = [i for i, e in enumerate(evidence) if e]
    return (weak, True) if len(weak) == 1 else ([], False)


# Sources

def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline='', encoding='utf-8-sig') as f:
        return list(csv.DictReader(f))


def load_cmt_authors(path: Path) -> dict[str, list[tuple[str, str]]]:
    """CMT ID -> [(name, email)]. 'Author Names' looks like 'Ann Lee (Uni A)*; Bo Park (Uni B; Lab C)'."""
    authors = {}
    for row in _read_csv(path):
        names = [n.split('(')[0].strip(' *') for n in re.split(r';(?![^()]*\))', row['Author Names'])]
        emails = [e.strip() for e in row['Author Emails'].split(';')]
        if len(names) != len(emails):
            raise ValueError(f'CMT {row["Paper ID"]}: {len(names)} names but {len(emails)} emails')
        authors[row['Paper ID']] = list(zip(names, emails))
    return authors


@dataclass(frozen=True)
class Registrant:
    name: str
    person: Person  # registration email, plus preferred emails if given
    claimed_papers: frozenset[str]  # CMT IDs, as typed into the registration form
    amount_due: float


def load_registrants(path: Path, preferred_emails: dict[str, list[str]] | None = None) -> list[Registrant]:
    """Rows of the registration export. preferred_emails: normalized registration email -> other emails to use."""
    if _local is None:
        raise RuntimeError('local/identity_local.py is missing: it names the registration form\'s paper number questions')
    preferred_emails = preferred_emails or {}
    return [
        Registrant(
            name=row['Full Name'],
            person=Person.of([row['Full Name']],
                             [row['Email Address'], *preferred_emails.get(normalize_email(row['Email Address']), [])]),
            # Every number counts, e.g. 'P12-7 (322)' claims 12, 7 and 322: an extra claim only adds weak evidence
            claimed_papers=frozenset(n.lstrip('0') for h in _local.PAPER_NUMBER_HEADERS for n in re.findall(r'\d+', row[h])),
            amount_due=float(row['Amount Due'] or 0),
        )
        for row in _read_csv(path)
    ]


def load_preferred_emails(path: Path) -> dict[str, list[str]]:
    """CSV with columns registration_email, preferred_email -> normalized registration email -> preferred emails."""
    preferred: dict[str, list[str]] = {}
    for row in _read_csv(path):
        if row['preferred_email'].strip():
            preferred.setdefault(normalize_email(row['registration_email']), []).append(row['preferred_email'])
    return preferred


@dataclass(frozen=True)
class SlackMember:
    user_id: str
    person: Person  # profile real name and display name, account email


def slack_members() -> tuple[SlackMember, ...]:
    """Active human members of the workspace selected by utils.slack.configure_clients; fetched once per workspace."""
    from utils import slack
    return _slack_members(slack.client_bot)


@functools.cache
def _slack_members(client) -> tuple[SlackMember, ...]:
    from utils import slack
    members = []
    for page in client.users_list(limit=slack.PAGE_LIMIT):
        for user in page['members']:
            if user.get('deleted') or user.get('is_bot') or user['id'] == 'USLACKBOT':
                continue
            profile = user['profile']
            names = [profile.get('real_name', ''), profile.get('display_name', ''), user.get('real_name', '')]
            members.append(SlackMember(user['id'], Person.of(names, [profile.get('email') or ''])))
    return tuple(members)
