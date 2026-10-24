import pytest

from utils.identity import Person, ambiguous_tokens, match_evidence, names_match, normalize_email, share_name_token


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
