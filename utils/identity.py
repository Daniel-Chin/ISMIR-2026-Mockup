'''
Deciding whether records from different sources (CMT, the registration export, Slack) are the same person.
The rules are name-agnostic and err towards false positives: a wrong match costs less than a missed one.
'''
import itertools
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass

# Letters that NFKD does not decompose into ASCII
_FOLD = str.maketrans({'ı': 'i', 'ł': 'l', 'ø': 'o', 'đ': 'd', 'ð': 'd', 'þ': 'th', 'ß': 'ss', 'æ': 'ae', 'œ': 'oe'})
_HONORIFICS = {'dr', 'prof', 'mr', 'mrs', 'ms', 'phd'}
_MAX_PERMUTED_TOKENS = 6


def name_tokens(name: str) -> tuple[str, ...]:
    """'Lee-Ørsted, Dr. Zoë A.' -> ('lee', 'orsted', 'zoe', 'a')"""
    folded = unicodedata.normalize('NFKD', name.lower().translate(_FOLD)).encode('ascii', 'ignore').decode()
    return tuple(t for t in re.findall(r'[a-z]+', folded) if t not in _HONORIFICS)


def _concatenations(tokens: tuple[str, ...]) -> set[str]:
    if len(tokens) > _MAX_PERMUTED_TOKENS:
        return {''.join(tokens)}
    return {''.join(p) for p in itertools.permutations(tokens)}


def _is_initial_of(a: str, b: str) -> bool:
    return (len(a) == 1 and b.startswith(a)) or (len(b) == 1 and a.startswith(b))


def names_match(a: str, b: str) -> bool:
    """
    Name-only evidence. Tolerates reordering, hyphens and spacing within names ('Zoe-Ann' = 'ZoeAnn'),
    initials ('Z. Lee' = 'Zoe Lee'), and dropped middle names or extra surnames ('Zoe Lee' = 'Zoe Ann Lee Park').
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


def share_name_token(a: str, b: str, ambiguous: frozenset[str] = frozenset()) -> bool:
    """Weak evidence: the names share a token longer than an initial, other than an ambiguous one."""
    return bool({t for t in name_tokens(a) if len(t) > 1} & set(name_tokens(b)) - ambiguous)


def normalize_email(email: str) -> str:
    """Drops '+tag' and, for Gmail, dots, since mail to those variants reaches the same inbox."""
    local, _, domain = email.strip().lower().partition('@')
    local = local.split('+', 1)[0]
    if domain in ('gmail.com', 'googlemail.com'):
        local, domain = local.replace('.', ''), 'gmail.com'
    return f'{local}@{domain}'


@dataclass(frozen=True)
class Person:
    names: frozenset[str]
    emails: frozenset[str]  # normalize_email applied

    @classmethod
    def of(cls, names: list[str], emails: list[str]) -> 'Person':
        return cls(frozenset(n for n in names if n.strip()), frozenset(normalize_email(e) for e in emails if e.strip()))


def match_evidence(a: Person, b: Person, related: bool = False, ambiguous: frozenset[str] = frozenset()) -> str | None:
    """
    Why a and b look like the same person, or None.
    related: an independent link exists (e.g. both are tied to the same paper), so a partial name suffices.
    ambiguous: tokens that don't count as a partial name, see ambiguous_tokens.
    """
    if a.emails & b.emails:
        return 'email'
    if any(names_match(x, y) for x in a.names for y in b.names):
        return 'name'
    if related and any(share_name_token(x, y, ambiguous) for x in a.names for y in b.names):
        return 'related + partial name'
    return None
