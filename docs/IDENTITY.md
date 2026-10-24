# Identity matching

[`utils/identity.py`](../utils/identity.py) decides whether records from different sources are the same
person: CMT authors (name + email per paper), the registration export (name + email + claimed paper
numbers), and later Slack members and their preferred emails.

The rules are generic and never mention specific people. They err towards **false positives**: inviting
someone to an extra channel costs little, but missing an author or registrant costs a lot. If a real case
fails, change it into a general rule (e.g. "initials match full names") rather than adding an alias table.

## Evidence

`match_evidence(a, b, related=False, ambiguous=frozenset())` compares two `Person`s (sets of names and
emails) and returns the strongest evidence it finds, or `None`:

| Evidence | Rule | Example |
|---|---|---|
| `email` | Emails are equal after `normalize_email`, which lowercases, drops `+tag`, and drops dots for Gmail | `Zoe.Lee+conf@GoogleMail.com` = `zoelee@gmail.com` |
| `name` | `names_match`, see below | `Lee, Zoe` = `Zoe A. Lee` |
| `related + partial name` | Only with `related=True`: the names share a word longer than an initial | `Zoe Ann Park` ~ `Park, Zoe` (Ann Park is the presenter, Zoe Park registered for that paper) |

Use `related=True` only when there is an independent link between the two records, for example a
registrant who entered the presenter's paper number. A shared word alone is too weak.

The checks run in the order of the table above, then the next table, and the first that holds is returned.
Only `email` and `name` count as strong. Everything else is weak evidence. Use weak evidence where false
positives are cheap, such as public paper channels, and ignore it where they aren't, such as paid tutorial
channels:

| Evidence | Rule | Example |
|---|---|---|
| `name variant` | `names_match(..., variants=True)`: as `name`, but words may also be short forms (both at least 3 letters) or differ by one letter or adjacent swap (both at least 5 letters). At least one word must still match exactly | `Chris Lee` ~ `Christopher Lee`, `Zoe Munroe` ~ `Zoe Murnoe` |
| `email resembles name` | `email_from_name`: the email handle, ignoring digits and punctuation, is made of the starts of two or more name words, including one whole word of 3+ letters and at most one initial | `zlee99@`, `zoe.le@` for `Zoe Ann Lee`; not `zalee@` |
| `similar email` | `similar_emails`: the same handle (5+ letters) at two providers, or handles that differ by one letter at the same provider | `zoelee@uni.example` ~ `zoelee@home.example` |

## Slack members and caching

`slack_members()` returns every active human member of the workspace chosen by
`utils.slack.configure_clients`. Each member's `Person` holds their profile real name, display name and
account email. It calls `users.list` once per workspace per process. Slack members go through the same
checks as everyone else.

The matching functions are cached in memory with `functools.cache` for the life of the process, so
comparing everyone with everyone stays fast. `ambiguous_tokens` is not cached, because callers often pass
it a generator.

### `names_match`

Names are first reduced to lowercase ASCII words by `name_tokens`: accents are removed, letters such
as `ı ł ø ß` are folded, punctuation splits words, and `Dr`, `Prof` and similar titles are dropped.
Two names match if either of these holds:

- The same letters can be joined in some word order. This handles reordering (`Lee, Zoe`), hyphens and
  spacing (`Zoe-Ann` = `ZoeAnn`).
- Every word of the shorter name lines up with a different word of the longer name, either exactly or as
  an initial (`Z.` = `Zoe`), and at least one word matches exactly. This handles initials and dropped
  middle names or second surnames. A single-word name never matches by this rule.

### Known-distinct people: `ambiguous_tokens`

People known to be different, such as the co-authors of one paper, give `ambiguous_tokens(names)`: the
words that appear in two or more of their names. Pass the result as `ambiguous` so those words don't
count as a partial name. If the paper has co-authors Zoe Lee and Amy Lee, the registrant `Lee, Amy` is not
taken to be Zoe through `lee`. This only blocks the weak evidence; a matching email or full name still
counts.

## Users

- [`scripts/less_generalizable/presenter_registration.py`](../scripts/less_generalizable/presenter_registration.py)
  reports papers whose presenter (`oral_session_presenter` in `papers.csv`) hasn't registered. It reads
  `local/cmt_authors.csv` and `local/registration/Registrant Details - latest.csv` by default (see
  `--help`). Presenters matched only by weak evidence are listed for a manual check.

  ```bash
  uv run python -m scripts.less_generalizable.presenter_registration
  ```

- [`modules/author_channels.py`](../modules/author_channels.py) (`--action invite-authors-to-channels`)
  adds authors to their paper and LBD channels, see [SLACK.md](SLACK.md).

Tests: `uv run --extra dev python -m pytest tests/test_identity.py tests/test_author_channels.py`. Use made-up names in tests, since
real attendee data stays in the gitignored `local/`.
