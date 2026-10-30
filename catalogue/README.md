# catalogue/ — assistant export stage

Builds the data artifacts the ISMIR Guide bot consumes (see `LLM_plan.md`).
This is the ONLY bridge between provisioning and the bot: the bot never reads
`sitedata/`, Google Sheets, or Drive.

Runs in the **root environment** (same as `main.py`); it reads `sitedata/*.csv`
like everything else. Must stay import-independent from `bot/` — `schema.py`
is the shared contract and is vendored into the bot image at build time.

## Operator loop (during the conference)

```bash
# 1. Pull fresh sheet data
python pull_from_google_sheet.py      # or: python pull_from_google_sheet.py --mockup

# 2. Build the catalogue (strips all private columns, validates schema)
python catalogue/build_catalogue.py --path sitedata/ --out-dir build/catalogue/

# 3. Build FTS5 index + embeddings (needs VOYAGE_API_KEY; --fake-embeddings for tests)
python catalogue/build_index.py --catalogue build/catalogue/catalogue-$(date +%F).json

# 4. Upload (dry run by default; --prod to actually upload)
python catalogue/upload.py --dir build/catalogue/ --version $(date +%F) \
    --bucket gs://<catalogue-bucket> --prod
```

The worker re-checks `latest.json` every 15 min — data fixes reach the bot
without a redeploy.

## Mock pipeline (end-to-end test, no keys needed)

```bash
python scripts/make_example_mock_data.py            # if sitedata_mock/ not present
python catalogue/build_catalogue.py --path sitedata_mock/ --out-dir build/catalogue_mock/ --version mock
python catalogue/build_index.py --catalogue build/catalogue_mock/catalogue-mock.json --fake-embeddings
python catalogue/upload.py --dir build/catalogue_mock/ --version mock --bucket gs://<test-bucket>
```

## Guarantees

- `author_emails`, `primary_email`, `organiser_emails`, `registered_emails`,
  `review1–4`, `meta_review` never appear in the output — the build fails if
  any private column key *or value* leaks through.
- Every paper's `slack_channel_id` is parsed from the `channel_url` the Slack
  prep writes back (both `app_redirect?channel=` and `/archives/` forms).
  Missing IDs are a warning, not an error, so the catalogue can be built
  before Slack prep runs.
- Paper day, session, and position come from the
  [assignment matrix](../docs/workflow.md#session-assignments). Session numbers
  join to `events.csv` titles `Oral/Poster Session - N`.
