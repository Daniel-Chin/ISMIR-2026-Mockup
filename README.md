# Welcome to ISMIR 2026 virtual platform creation code!!

> **Docs:** [docs/workflow.md](docs/workflow.md) — full pipeline reference (data formats, Slack/Zoom automation, deploy). [docs/SPREADSHEET_FORMAT.md](docs/SPREADSHEET_FORMAT.md) — master Google Sheet tabs/columns the pipeline expects. [docs/repeatable_workflows.md](docs/repeatable_workflows.md) — repeatable jobs, e.g. digesting new author uploads (form → Live Database → videos → YouTube). [docs/YOUTUBE.md](docs/YOUTUBE.md) — presentation videos on YouTube. [docs/MOCKUP.md](docs/MOCKUP.md) — 3-hour mock conference runbook with generated test data (`scripts/make_mock_data.py` → `sitedata_mock/`). [docs/ZOOM.md](docs/ZOOM.md) — Zoom integration: S2S OAuth setup, `setup-zoom`, poster breakout rooms. [docs/SLACK.md](docs/SLACK.md) — Slack integration: bot app setup, `setup-papers-*` channel pipeline, invites, topic/purpose. [docs/IDENTITY.md](docs/IDENTITY.md) — matching people across CMT, registration and Slack (`utils/identity.py`). [docs/ASSISTANT.md](docs/ASSISTANT.md) — ISMIR Guide LLM assistant: catalogue export (`catalogue/`), Slack bot (`bot/`), setup, operator loop, guardrails. [docs/SPONSORS.md](docs/SPONSORS.md) — sponsor logos on the Industry event page (`sitedata/sponsors/`).

Run with Python 3.12

1. Clone this repo 
2. Run `>> python miniconf_prep.py` this will prepare the data as required by miniconf. Read through this code for the details of preprocessing
3. To build the miniconf site and run it locally try: `>> export FLASK_DEBUG=True; export FLASK_DEVELOPMENT=True; python main.py`
4. To build the site in production push the committed changes to the `main` branch of remote.

## Contributing Guidelines

- Always pull the latest changes from `main` branch before making any changes.
- Check if there are pull requests (PRs) that are related to your intended changes before starting your work.
- Commit to the `main` branch is allowed, but please try to encompass the feature or bug fix in a single commit.
- If multiple commits are needed, please ensure that each commit does not break the build.
- For major changes that requires time, please work on a separate branch and create a PR to let others know.
    - Have at least one other person review your PR is encouraged but not required.
- Try to keep each PR small and focused on a single issue or feature.
- Merge PRs using __squash and merge__ to keep the commit history clean.


## Paper Slack Channel Setup

For mockup runs, add `--mockup` to prep commands; these
use `MOCKUP_SLACK_BOT_TOKEN` and `MOCKUP_SLACK_USER_TOKEN` from `.env`.

See [docs/SLACK.md](docs/SLACK.md) for the full pipeline (app/token setup, what each step does, idempotence, troubleshooting). Short version:

```bash
export SLACK_BOT_TOKEN=...
export SLACK_USER_TOKEN=...

# create channel with the given name, add channel link to the data sheet
python miniconf_prep.py --action setup-papers-create-channels

# the following two orders don't matter
# invite authors to their paper and LBD channels
python miniconf_prep.py --action invite-authors-to-channels

# add paper-channel metadata, including the poster-session Slack link and miniconf link
python miniconf_prep.py --action setup-papers-set-desc

# set event/channel descriptions for all event rows with link to live Zoom
python miniconf_prep.py --action set-event-channel-desc
```

## Repo lineage
Previous private repos contain conference-specific commits so the commit history is severed:
https://github.com/nkundiushuti/ismir2026-virtual-sim  
https://github.com/Daniel-Chin/ismir2026-virtual-sim  
