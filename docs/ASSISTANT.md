# ISMIR Guide — LLM conference assistant

An LLM-powered Slack assistant ("ISMIR Guide") that answers attendee
questions about papers, authors, sessions, schedule and conference
logistics. Design rationale: [`../LLM_plan.md`](../LLM_plan.md). Component
docs: [`../catalogue/README.md`](../catalogue/README.md) (export stage) and
[`../bot/README.md`](../bot/README.md) (services, dev loop).

Scale target: ~300 participants, ~300–500 papers + LBDs, ~2 weeks active,
tens of dollars of total LLM spend.

## Architecture

```
sitedata/*.csv ── catalogue/build_catalogue.py     (strips private columns,
       │                    │                       validates schema)
  (existing         catalogue-<date>.json
   pipeline)                │
                   catalogue/build_index.py        (FTS5 sqlite + Voyage
                            │                       embeddings)
                   catalogue/upload.py --prod ───► GCS bucket (+ latest.json)
                                                        │  polled every 15 min
                                                        ▼
Slack (DM / @mention / /ask-ismir / buttons)
   │
   ▼
Cloud Run "ingress"  (bot/ingress/)                 public
   · Slack signature + timestamp verification (Bolt)
   · deterministic pre-checks: 2,000-char cap, no attachments
   · per-user daily limit (20 questions/day) — rejected before any cost
   · ack < 3 s: posts a "Searching…" placeholder
   · enqueues a Cloud Task (job_id = Slack event_id)
   ▼
Cloud Tasks queue    (retries, global concurrency cap = queue setting)
   ▼
Cloud Run "worker"   (bot/worker/)                  private (OIDC only)
   · idempotency: jobs/{job_id} in Firestore, claimed exactly once
   · per-user concurrency 1
   · daily spend cap (Firestore counter) → canned reply + admin DM
   · scope gate: conference-term regex → embedding similarity → FTS entity
     hit → Haiku yes/no only in the ambiguous zone
   · Claude tool loop (Sonnet-class, config): hybrid retrieval (BM25 +
     cosine, RRF), schedule/author/logistics tools, profile tools
   · grounding: cited MiniConf links must exist in the catalogue; one
     corrective retry, then "couldn't find"
   · chat.update of the placeholder (Block Kit + paper buttons)
```

The catalogue is the ONLY bridge between provisioning and the bot. The bot
never reads `sitedata/`, Google Sheets or Drive; the export never contains
`author_emails`, `primary_email`, `organiser_emails`, `registered_emails`,
`review1–4` or `meta_review` (build fails if a key *or value* leaks).

| Piece | Where | Runs |
|---|---|---|
| Catalogue export | `catalogue/` | root env, operator machine, manual |
| Ingress service | `bot/ingress/` | Cloud Run, public |
| Worker service | `bot/worker/` | Cloud Run, private (Cloud Tasks OIDC) |
| Shared config / catalogue loader / limits | `bot/shared/` | both services |
| Schema contract | `catalogue/schema.py` | vendored into bot image at build |
| Deploy | `infra/deploy_bot.sh` + `infra/cloudbuild.yaml` | operator / CI |
| CI | `.github/workflows/bot-deploy.yml` | GitHub Actions, path-filtered to `bot/**` + `infra/**` |

## Interaction model

One backend, four entry points:

1. **DM** with the app (primary; threaded multi-turn).
2. **@ISMIR Guide** mention in designated channels (replies in-thread).
3. **`/ask-ismir <question>`** slash command (one-shot fallback).
4. **Buttons** on paper answers — `Save paper`, `More like this`,
   `Not relevant`, `Add to my schedule` — handled deterministically
   (profile writes + embedding math, zero LLM cost).

User profiles (`profiles/{slack_user_id}` in Firestore) hold saved papers,
rejections, feedback and availability. DM-ing exactly
`delete my ismir preferences` wipes the profile. Delete all profiles 30
days post-conference unless opted in.

## One-time setup

1. **Slack app** — create "ISMIR Guide" from
   [`../bot/slack-app-manifest.yml`](../bot/slack-app-manifest.yml) in the
   workspace (a *separate* app from the provisioning bot in
   [SLACK.md](SLACK.md)). Install; note bot token + signing secret.
2. **GCP** (full list in the header of `infra/deploy_bot.sh`): project,
   Artifact Registry repo `ismir-guide`, Firestore (native) with TTL policy
   on collection `jobs` field `expires_at`, Cloud Tasks queue (queue
   concurrency = the global cap), catalogue GCS bucket, ingress/worker
   service accounts, Secret Manager secrets `ismir-guide-slack-bot-token`,
   `ismir-guide-slack-signing-secret`, `ismir-guide-anthropic-key`,
   `ismir-guide-voyage-key`.
3. **Deploy**: `PROJECT=<p> REGION=<r> ./infra/deploy_bot.sh`, then set the
   printed ingress URL (path `/slack/events`) as the Slack app's request
   URL / slash-command URL / interactivity URL and re-apply the manifest.
4. **Data prerequisites** (existing workflows): 2026 `sitedata/` via
   `python pull_from_google_sheet.py`; `setup-papers-create-channels` +
   `setup-lbd` run so `channel_url` is populated; add a `logistics` tab
   (columns `id,title,body`) to the master Sheet and a matching update in
   `pull_from_google_sheet.py`; validate the join between
   [the assignment matrix](workflow.md#session-assignments) and `events.csv`
   on 2026 data.
5. **Tune the scope gate**: with real embeddings,
   `cd bot && CATALOGUE_DIR=../build/catalogue uv run python
   evals/run_scope_eval.py`, adjust `SIM_STRONG`/`SIM_WEAK` in
   `bot/worker/scope_gate.py`.

## Operator loop during the conference

Data fixes reach the bot within ~15 minutes, no redeploy:

```bash
python pull_from_google_sheet.py                 # Sheet -> sitedata/
python catalogue/build_catalogue.py --path sitedata/ --out-dir build/catalogue/
python catalogue/build_index.py --catalogue build/catalogue/catalogue-$(date +%F).json
python catalogue/upload.py --dir build/catalogue/ --version $(date +%F) \
    --bucket gs://<catalogue-bucket> --prod
```

Code changes to `bot/**`/`infra/**` deploy via CI on push to main (or
`infra/deploy_bot.sh` manually). Provisioning edits can never trigger a bot
deploy — the workflow is path-filtered.

## Guardrails & cost

| Guardrail | Where | Default |
|---|---|---|
| Input cap 2,000 chars, no attachments | ingress | — |
| Per-user daily question limit | ingress | `PER_USER_DAILY_LIMIT=20` |
| Per-user concurrency 1 | worker | — |
| Global concurrency | Cloud Tasks queue setting | set at queue creation |
| Daily spend cap | worker (Firestore counter) | `MAX_DAILY_SPEND_USD=20` |
| Admin alert on cap (once/day) | worker → DM | `ADMIN_USER_IDS=U1,U2` |
| Max 3 tool rounds, capped output tokens | agent loop | — |
| Grounding validation before posting | worker | — |

Models are config, not code: `AGENT_MODEL` (Sonnet-class default),
`SCOPE_MODEL` (Haiku-class), `EMBEDDING_MODEL` (voyage-3.5). Recompute the
cost estimate from live pricing before the conference and set
`shared/limits.py` `PRICES` to match the chosen agent model.

## Testing without any external services

```bash
# mock catalogue artifacts (no keys: deterministic fake embeddings)
python scripts/make_example_mock_data.py
python catalogue/build_catalogue.py --path sitedata_mock/ --out-dir build/catalogue_mock/ --version mock
python catalogue/build_index.py --catalogue build/catalogue_mock/catalogue-mock.json --fake-embeddings

# bot test suite (LOCAL_MODE: in-memory stores, direct-HTTP queue)
cd bot && uv sync && uv run pytest

# local worker against the mock catalogue + load test
LOCAL_MODE=1 CATALOGUE_DIR=../build/catalogue_mock uv run python -m worker.app &
uv run python evals/load_test.py --n 50
```

## Troubleshooting

| Symptom | Check |
|---|---|
| Placeholder never updates | worker logs; Cloud Tasks queue backlog; worker OIDC (`run.invoker` for the queue SA) |
| "temporarily unavailable" answers | daily spend cap hit — `counters/spend:<yyyymmdd>` in Firestore |
| Answers missing Slack channel links | `channel_url` empty in CSVs → run Slack prep, re-export catalogue |
| Everything out-of-scope / in-scope | thresholds vs embedding model mismatch — re-run `evals/run_scope_eval.py` |
| Data fix not showing after 15 min | did `upload.py --prod` run? `latest.json` version bumped? |
| Duplicate answers | `jobs` TTL policy missing (claims never expire) |

## Deferred (post-v1)

Ephemeral @mention replies with a "Share to channel" button; App Home tab
(delete-preferences button); Slack Assistant suggested prompts; multi-turn
thread context fetch.
