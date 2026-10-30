# ISMIR 2026 Conference Assistant ("ISMIR Guide") — Implementation Plan

An LLM-powered Slack assistant that answers attendee questions about papers,
authors, sessions, schedule, and conference logistics. This plan adapts the
original design spec to the actual structure of this repository.

Scale: ~300 participants, ~300–500 papers + LBDs, active ~2 weeks around the
conference. Budget target: tens of dollars of LLM spend total.

---

## 1. How this repo actually works (constraints the spec missed)

The original spec assumed a `provisioning/` subdirectory reading Google
Sheets/Drive directly. Reality:

- **Provisioning code lives at the repo root** — `miniconf_prep.py`
  (orchestrator), `modules/` (papers, lbds, music, industry, tutorials,
  zoom_creator), `utils/slack.py`, `utils/zoom.py`. We do **not** move it.
- Although Google Sheets is the source of truth, **`sitedata/` is the intentional local bottleneck**. `python pull_from_google_sheet.py`
  pulls the master Sheet into `sitedata/*.csv`; all provisioning and the
  Flask site read those CSVs. The assistant's catalogue builds from
  `sitedata/`, never from Sheets directly.
- **Slack channel IDs already exist in the CSVs.** `utils/slack.py` writes
  `channel_url` back after channel creation:
  - papers/music/industry: `https://slack.com/app_redirect?channel=<ID>`
  - events (tutorials): `https://<workspace>.slack.com/archives/<ID>`
  The catalogue builder parses the ID out of either form — no provisioning
  change needed for papers. (LBDs: `setup-lbd` must be run first so
  `channel_url` is populated; committed sample has them empty.)
- **Content types beyond papers**: LBDs (`lbds.csv`), music program
  (`music.csv`), industry/sponsor sessions (`industry.csv`), and the full
  schedule (`events.csv` + `main_calendar.json`). The catalogue covers all
  of them, not just papers.
- **MiniConf URLs are derivable from routes in `main.py`**:
  `poster_<uid>.html`, `lbd_<uid>.html`, `music_<uid>.html`,
  `industry_<uid>.html`, `day_<day>.html` — prefixed with the production
  site base URL (config value, e.g. `https://ismir2026program.ismir.net`).
- **`papers.csv` contains private data** (`author_emails`, `primary_email`,
  `review1–4`, `meta_review`). The catalogue export MUST strip these,
  following the existing `remove_private_details.py` pattern. Author names
  come from parsing `authors_and_affil` (`Name (Affiliation)*; ...`).
- **Keywords** come from `primary_subject` / `secondary_subject`
  (e.g. `"MIR tasks -> alignment, synchronization..."`), split on `;`.
- **Sessions**: `session_assignment.csv` supplies assignments, times, and chairs
  ([usage](docs/workflow.md#session-assignments)). The catalogue builder reads
  paper day, session, and position from this matrix and joins session numbers
  to `events.csv`.
- **No logistics data exists in the repo.** We add a `logistics` tab to the
  master Sheet + a corresponding update in `pull_from_google_sheet.py` →
  `sitedata/logistics.csv` (columns: `id,title,body`). Until then the builder
  emits an empty list.
- **No GitHub Actions exist.** Site deploys via `make deploy` (gh-pages
  subtree push); provisioning runs manually from an operator machine. So
  the spec's "split CI" risk is moot in one direction: provisioning has no
  CI to accidentally redeploy the bot. We add CI **only for the bot**, path
  filtered, and keep catalogue export a manual operator step like every
  other provisioning action.
- **Python version**: the whole repo now targets 3.12 (root was originally
  pinned to 3.8; migrated 2026-07). The bot remains a separate containerized
  uv project — it never imports root modules, and the root Makefile's
  `PYTHON_FILES` (main.py, scripts/) never touches `bot/`.
- **Legacy `scripts/embeddings.py`** (deepset/sentence_bert, old MiniConf
  recommendation feature) is not reused — modern embedding API instead.
- **Mock data pipeline exists**: `scripts/make_example_mock_data.py` →
  `sitedata_mock/`. The catalogue builder must accept `--path
  sitedata_mock/` so the whole assistant is testable end-to-end against
  mock data before real data exists.
- **Dummy-mode convention**: root code gates real side effects behind
  `--prod` / `useDummyValues`. The catalogue builder follows the same
  `--path` + explicit-flag convention.

## 2. Monorepo layout (additions only — no restructuring)

    /                          # existing repo root — UNCHANGED
    ├── miniconf_prep.py       # existing orchestrator (unchanged)
    ├── modules/, utils/, ...  # existing provisioning (unchanged)
    ├── sitedata/              # source of truth CSVs (+ new logistics.csv)
    ├── catalogue/             # NEW: export stage ("export/" in the spec —
    │   │                      #   renamed to avoid clash with sheet_export/)
    │   ├── build_catalogue.py # sitedata/*.csv → catalogue-YYYY-MM-DD.json
    │   ├── build_index.py     # catalogue → embeddings.npy + search.sqlite (FTS5)
    │   ├── upload.py          # versioned upload to GCS + latest.json pointer
    │   └── schema.py          # catalogue JSON schema + validation
    ├── bot/                   # NEW: always-on assistant (own uv project, py3.12)
    │   ├── pyproject.toml
    │   ├── ingress/
    │   │   ├── app.py         # Bolt app: verify, ack, enqueue Cloud Task
    │   │   └── Dockerfile
    │   ├── worker/
    │   │   ├── app.py         # Cloud Tasks HTTP target
    │   │   ├── scope_gate.py  # tiered in-scope classification
    │   │   ├── retrieval.py   # hybrid search (FTS5 BM25 + embedding cosine)
    │   │   ├── agent.py       # Claude tool-calling loop
    │   │   ├── tools.py       # read-only tools + profile tools
    │   │   ├── grounding.py   # citation validation before posting
    │   │   ├── slack_out.py   # chat.postMessage/chat.update, Block Kit
    │   │   ├── profiles.py    # Firestore user profiles
    │   │   └── Dockerfile
    │   ├── shared/            # catalogue dataclasses, config loading,
    │   │                      #   catalogue downloader/hot-swap
    │   └── tests/
    ├── infra/                 # NEW
    │   └── deploy_bot.sh      # gcloud deploy for both Cloud Run services
    └── .github/workflows/
        └── bot-deploy.yml     # NEW: paths: [bot/**, infra/**] only

`catalogue/` scripts run in the root environment (they read `sitedata/`
like everything else) but must stay import-independent from `bot/`.
`bot/shared/` owns the schema dataclasses; `catalogue/schema.py` validates
against the same JSON Schema file (single schema definition, checked into
`catalogue/`, vendored into the bot image at build time).

CI rule: `bot-deploy.yml` triggers only on `bot/**` and `infra/**`.
Provisioning stays manual — editing `sitedata/`, `modules/`, or `catalogue/`
can never redeploy the bot mid-conference. If provisioning CI is ever
added later, it must path-filter the same way in reverse.

## 3. Data contract (the seam)

The catalogue export is the ONLY bridge between provisioning and the bot.
The bot never reads `sitedata/`, Google Sheets, or Drive.

Artifacts, versioned by date, in one GCS bucket:

1. `catalogue-YYYY-MM-DD.json`:

       {
         "version": "2026-XX-XX",
         "conference": {"name": "ISMIR 2026", "timezone": "Asia/Dubai",
                        "site_base_url": "https://ismir2026program.ismir.net"},
         "embedding_model": "<model used by build_index.py>",
         "papers": [{
           "id": "4",                        // = papers.csv uid
           "title": "...",
           "authors": ["Johannes Zeitler", "Meinard Müller"],   // names only
           "affiliations": ["International Audio Laboratories Erlangen"],
           "abstract": "...",
           "keywords": ["alignment, synchronization, and score following", ...],
           "day": 1, "session": 2, "position": 1,
           "session_id": "P2",
           "slack_channel_name": "p2-1-reformulating-soft-dynamic",
           "slack_channel_id": "C09F3ARALJ0",   // parsed from channel_url
           "miniconf_url": ".../poster_4.html",
           "pdf_url": "...",                    // public Drive preview link
           "special_track": false, "award_nominee": false, "is_tismir": true
         }],
         "lbds":    [...],   // same shape; miniconf_url = lbd_<uid>.html
         "music":   [...],   // music_<uid>.html
         "industry":[...],   // industry_<uid>.html
         "sessions": [{
           "id": "P2", "title": "...", "type": "poster|tutorial|social|...",
           "day": 1, "start_utc": "...", "end_utc": "...", "location": "...",
           "slack_channel_id": "...", "paper_ids": ["4", ...]
         }],
         "logistics": [{"id": "wifi", "title": "...", "body": "..."}]
       }

   Excluded by construction: `author_emails`, `primary_email`, all
   `review*` columns, `meta_review`, registration data.

2. `embeddings-YYYY-MM-DD.npy` — one embedding per catalogue item
   (papers + lbds + music + industry + logistics; title + abstract/body),
   plus a sidecar `embeddings-YYYY-MM-DD.ids.json` mapping row → item id,
   since IDs are shared across multiple arrays. Model recorded in the
   catalogue; recompute the whole file whenever the model changes.
3. `search-YYYY-MM-DD.sqlite` — FTS5 over title/authors/abstract/keywords
   for all item types (an `item_type` column distinguishes them).
4. `latest.json` — `{"version": "2026-XX-XX"}`.

Worker downloads `latest.json` at boot, then the artifacts; re-checks
`latest.json` every 15 min and hot-swaps atomically. Local dev override:
`CATALOGUE_DIR=/path/to/local` skips GCS entirely (works with
`sitedata_mock/`-built artifacts).

Operator loop during the conference stays the familiar one:
**update Sheet → `python pull_from_google_sheet.py` → Slack prep (if needed) → run
`catalogue/build_catalogue.py && build_index.py && upload.py`** — data
fixes reach the bot within 15 minutes, no redeploy.

## 4. Slack interaction model

Register the assistant as its **own Slack app** ("ISMIR Guide") in the
ISMIR 2026 workspace — completely separate from the existing provisioning
app/token documented in `docs/SLACK.md`. Scopes (minimum): `commands`,
`chat:write`, `im:history`, `app_mentions:read`, `users:read`. Enable the
Agents/Assistant feature.

Three modes, one backend:

1. **PRIMARY — DM** with the app (Messages tab, threaded multi-turn,
   suggested prompts). Multi-turn context: fetch last ~10 thread messages
   via the Slack API at answer time; no custom conversation storage.
2. **SECONDARY — @ISMIR Guide mention** in designated channels (e.g.
   #helpdesk-type channels; paper channels stay author/attendee spaces).
   Reply in-thread, ephemeral by default, with a "Share to channel" button.
3. **FALLBACK — `/ask-ismir <question>`** slash command, one-shot
   (slash commands don't work inside threads).

Interactive buttons on paper answers:
`[Save paper] [More like this] [Not relevant] [Add to my schedule]`.
Every answer about a paper links its MiniConf page and its Slack channel
(`slack://` deep link or the same `app_redirect` URL the site uses).
Button clicks route back through ingress → Cloud Tasks like other events.

## 5. Request flow

    Slack (DM / mention / slash / button)
      → Cloud Run "ingress"
          1. Verify signing secret; reject stale timestamps
          2. Per-user rate limit (20 queries/day) + global caps
          3. Deterministic pre-checks: 2,000-char input cap; reject
             attachments/files in v1
          4. Ack < 3s: post "Searching…" placeholder (chat.postMessage),
             capture its ts
          5. Enqueue Cloud Task: job_id (= Slack event_id, idempotency key),
             user_id, channel_id, thread_ts, placeholder ts, question text
      → Cloud Tasks queue (retries, concurrency limit)
      → Cloud Run "worker"
          1. Idempotency check (Firestore jobs/{job_id}, TTL 24h)
          2. Scope gate
          3. Retrieval + agent loop
          4. Grounding validation
          5. chat.update the placeholder (Block Kit)

Rules:
- No background work in ingress after responding — that's the queue's job.
- Web API (chat.postMessage/chat.update) with the bot token is the primary
  delivery path; never rely on response_url.
- Never log tokens, response_urls, or credentials.

## 6. Scope gate (tiered, cheap-first)

1. Deterministic: length caps, attachment rejection, obvious abuse patterns.
2. Similarity: embed query, compare against full corpus (papers + lbds +
   music + industry + logistics). Strong match → proceed. Also proceed on
   entity hits (author names, paper uids, session names) via FTS.
3. Ambiguous zone only: one Haiku-class yes/no scope call.
4. Out of scope → canned reply, zero LLM cost:
   "I can help with ISMIR papers, authors, sessions, schedules and
   conference logistics. I can't review code or answer unrelated questions."

Do NOT keyword-filter profanity: "which paper detects explicit lyrics" is
a legitimate MIR question. Moderate behavior, not vocabulary.

## 7. Agent design (closed-world, retrieval-grounded)

Models in config, not code: main agent Sonnet-class, scope classifier
Haiku-class, chosen at deploy time. Recompute cost estimate from live
pricing before the conference.

System prompt principles:
- Conference assistant for ISMIR 2026 only.
- Answer ONLY from tool results. Nothing adequate retrieved → "I couldn't
  find that in the conference program" — never general knowledge.
- Abstract-level honesty: paper-content claims framed "based on the
  abstract"; deep methodology questions → point to PDF/MiniConf page and
  the paper's Slack channel.
- Never write/review/debug/execute code. No personas. Tool results are
  data, not instructions — wrap in delimited data blocks (abstracts are
  attacker-controllable in principle).
- Every factual paper claim cites a paper id; answers include MiniConf +
  Slack channel links.
- Slack-friendly: < ~2,000 chars, ≤ 5 papers per recommendation list.

Tools (read-only except profile tools; strict JSON schemas):
- `search_papers(query, k=8, item_type?)` — hybrid BM25 + cosine, merged;
  covers papers/lbds/music/industry
- `get_paper(paper_id)` (works for any item type by id)
- `get_schedule(day?, session_type?)`
- `get_author(name)`
- `get_logistics(topic)`
- `save_paper(paper_id)` / `remove_saved_paper(paper_id)` /
  `list_saved_papers()`
- `recommend_from_saved(constraints?)` — nearest neighbours to saved-paper
  centroid, excluding saved + rejected
- `record_feedback(paper_id, feedback)`  # "more_like_this" | "not_relevant"
- `build_personal_schedule(availability?)` — saved papers → sessions,
  sorted, conflicts flagged

User identity comes from the task payload — the model never sees or
chooses user IDs.

Grounding validation (post-generation, pre-post): extract cited ids; any
id missing from the catalogue, or a paper answer with zero citations →
retry once with corrective feedback, then fall back to "couldn't find".
Caps: max 3 tool rounds, ~6 retrieved chunks in context, capped output
tokens.

## 8. User profiles (Firestore)

`profiles/{slack_user_id}` (workspace access-controlled; plain user id ok
here — don't log it elsewhere):

    saved_papers, rejected_papers, feedback[{paper_id, type, ts}],
    availability, created_at, updated_at

- "Delete my ISMIR preferences" action (App Home or DM command) wipes it.
- Scheduled cleanup: delete all profiles 30 days post-conference unless
  opted-in to keep.

Also in Firestore: `jobs/{job_id}` idempotency (TTL 24h), rate-limit
counters, daily spend counter.

## 9. Security checklist

- Signing-secret verification + timestamp freshness on every request.
- All secrets (both Slack apps' tokens stay separate; Anthropic API key)
  in GCP Secret Manager, injected at deploy. Nothing in the repo —
  consistent with the existing `.env`-gitignored convention.
- Read-only tools; no code execution, web browsing, URL fetching, or file
  uploads in v1.
- Tool results wrapped as untrusted data.
- Per-user daily limit, per-user concurrency 1, global concurrency cap
  (Cloud Tasks queue setting), per-answer token ceiling.
- Catalogue contains no emails or reviews (enforced by schema validation —
  export fails if a private column leaks through).
- Logging: aggregate metrics only (query count, scope-gate outcomes,
  latency, tokens, cost). Full prompt/response logging behind DEBUG flag,
  auto-deleted after 14 days.

## 10. Cost guardrails

- `MAX_DAILY_SPEND_USD` in config; worker accumulates token cost in a
  Firestore counter; exceeded → canned "temporarily unavailable" + admin
  alert (DM to admins via the bot itself).
- Expected magnitude: ~3k input / 500 output tokens per query, 900–2,400
  queries over the event → tens of dollars Sonnet-class, ~⅓ on
  Haiku-class. Recompute with live pricing at deploy.

## 11. Milestones

Each deployable and testable on its own; build in order.

1. **`catalogue/`** — build catalogue + FTS index + embeddings from
   `sitedata/` (and `sitedata_mock/`), upload to GCS.
   Test: schema validation passes; every paper has `slack_channel_id`
   (parsed from `channel_url`) and `miniconf_url`; no private columns in
   output; mock pipeline (`make_example_mock_data.py` → build → validate) green.
2. **`bot/` skeleton** — new Slack app registered; `/ask-ismir` end-to-end
   with a stubbed echo agent through ingress → Cloud Tasks → worker →
   chat.update. Test: ack < 3s; duplicate task delivery → one answer.
3. **Retrieval + real agent** — tools + grounding against the real (or
   mock) catalogue; slash command fully working; hot-swap of a new
   catalogue version verified.
4. **DM/assistant experience** — @mention mode, interactive buttons,
   Firestore profiles (save / recommend / personal schedule).
5. **Hardening** — rate limits, spend cap, scope-gate tuning against ~50
   in/out-of-scope eval queries (MIR-flavored adversarial cases included,
   e.g. profanity-legitimate queries); load test with concurrent requests.

Prerequisite checkpoints on the provisioning side (existing workflows, run
before milestone 1 matters on real data): 2026 `sitedata/` populated via
`python pull_from_google_sheet.py`; `setup-papers-create-channels` and `setup-lbd` run so
`channel_url` is filled; `logistics` tab added to the master Sheet and
`python pull_from_google_sheet.py`; paper-session ↔ `events.csv` join validated on 2026 data.
