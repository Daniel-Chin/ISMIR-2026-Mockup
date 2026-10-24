import pytest

from utils.identity import (
    Person, ambiguous_tokens, email_from_name, match_evidence, names_match, normalize_email, share_name_token,
    similar_emails,
)


@pytest.mark.parametrize('a, b', [
    ('Lee, Zoe', 'Zoe Lee'),
    ('Zoë Ørsted', 'Zoe Orsted'),
    ('Işık Ay', 'Isik Ay'),
    ('Dr. Zoe Lee', 'Zoe Lee'),
    ('ZoeAnn Lee', 'Lee, Zoe-Ann'),
    ('Z. Lee', 'Zoe Lee'),
    ('Zoe K', 'Karr, Zoe'),
    ('Zoe R. Lee', 'Zoe Robert Lee'),
    ('Zoe Lee', 'Zoe A. B. Lee'),
    ('Lee, Zoe', 'Zoe Ann Lee-Park'),
])
def test_names_match(a, b):
    assert names_match(a, b)
    assert names_match(b, a)


@pytest.mark.parametrize('a, b', [
    ('Zoe Lee', 'Amy Lee'),
    ('Zoe', 'Zoe Lee'),
    ('Z L', 'Zoe Lee'),
])
def test_names_differ(a, b):
    assert not names_match(a, b)


def test_share_name_token_ignores_initials():
    assert share_name_token('Zoe Lee', 'Lee, Amy')
    assert not share_name_token('Z Lee', 'Zed Ray')


def test_normalize_email():
    assert normalize_email(' Zoe.Lee+conf@GoogleMail.com ') == 'zoelee@gmail.com'
    assert normalize_email('Zoe.Lee+conf@uni.example') == 'zoe.lee@uni.example'


def test_match_evidence():
    presenter = Person.of(['Zoe Lee'], ['zoe@uni.example'])
    assert match_evidence(presenter, Person.of(['Someone Else'], ['ZOE@uni.example'])) == 'email'
    assert match_evidence(presenter, Person.of(['Lee, Zoe'], ['z@home.example'])) == 'name'
    namesake = Person.of(['Lee, Amy'], ['amy@uni.example'])
    assert match_evidence(presenter, namesake) is None
    assert match_evidence(presenter, namesake, related=True) == 'related + partial name'


def test_coauthor_namesakes_are_not_partial_evidence():
    ambiguous = ambiguous_tokens(['Zoe Lee', 'Amy Lee', 'Bo Park'])
    assert ambiguous == {'lee'}
    presenter = Person.of(['Zoe Lee'], ['zoe@uni.example'])
    assert match_evidence(presenter, Person.of(['Lee, Amy'], ['amy@uni.example']), True, ambiguous) is None
    assert match_evidence(presenter, Person.of(['Lee-Park, Zoe'], ['z@home.example']), True, ambiguous) == 'name'


@pytest.mark.parametrize('a, b, expected', [
    ('Chris Lee', 'Lee, Christopher', True),
    ('Zoe Mueller', 'Zoe Müller', True),
    ('Zoe Munroe', 'Zoe Murnoe', True),
    ('Zoe Lee', 'Zoe Lea', False),  # a typo needs 5+ letters
    ('Bo Cheung', 'Cheng, Bob', False),  # no word matches exactly
])
def test_names_match_variants(a, b, expected):
    assert not names_match(a, b)
    assert names_match(a, b, variants=True) == expected


@pytest.mark.parametrize('email, expected', [
    ('zlee99@uni.example', True),
    ('zoe.le@uni.example', True),
    ('annlee@uni.example', True),
    ('zle@uni.example', False),  # no whole word
    ('zalee@uni.example', False),  # two initials
    ('lee@uni.example', False),  # one word
])
def test_email_from_name(email, expected):
    assert email_from_name(email, 'Zoe Ann Lee') == expected


def test_similar_emails():
    assert similar_emails('zoelee@uni.example', 'zoelee@home.example')
    assert similar_emails('zoelee@gmail.com', 'zoeele@gmail.com')
    assert not similar_emails('zlee@uni.example', 'zlee@home.example')  # handle too short
    assert not similar_emails('zoelee@uni.example', 'zoeele@home.example')


def test_weak_evidence_needs_no_related_link():
    presenter = Person.of(['Zoe Munroe'], ['zoe@uni.example'])
    assert match_evidence(presenter, Person.of(['Murnoe, Zoe'], ['z@home.example'])) == 'name variant'
    assert match_evidence(presenter, Person.of(['Someone'], ['zoemunroe@home.example'])) == 'email resembles name'
    assert match_evidence(Person.of(['A'], ['zoelee@uni.example']), Person.of(['B'], ['zoelee@home.example'])) == 'similar email'
