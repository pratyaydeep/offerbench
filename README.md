# offerbench

Benchmark offers from different organizations.

Tracks compensation discussion posts from LeetCode's discuss forum
(`compensation` tag), extracts structured data (organization, role,
compensation breakdown, etc.) from each post via an LLM, and serves a local
dashboard for lookups like "SDE2 roles paying ≥40 lakhs".

See `findings.md` for how the underlying LeetCode GraphQL API works.

## Setup

```bash
uv sync
cp .env.example .env
```

Edit `.env` and point it at any OpenAI-compatible LLM provider/model, e.g.:

```
LLM_BASE_URL=https://openrouter.ai/api/v1
LLM_API_KEY=...
LLM_MODEL=anthropic/claude-3.5-sonnet
```

(OpenRouter, NVIDIA build, and OpenAI itself all work — just change
`LLM_BASE_URL`/`LLM_MODEL`. Pick a model that supports tool/function
calling, since that's how structured extraction works.)

## Usage

```bash
uv run offerbench sync       # fetch new posts (auto-backfills everything on an empty DB)
uv run offerbench extract    # run LLM extraction on posts pending it
uv run offerbench status     # show pipeline counts
uv run offerbench serve      # start the local dashboard at http://127.0.0.1:5000
```

Useful flags:

```bash
uv run offerbench extract --limit 20   # cap batch size while iterating on the prompt
uv run offerbench extract --force      # re-extract everything at the current extraction version
```

There's no scheduler wired up yet — run `sync`/`extract` manually (e.g. from
cron) whenever you want fresh data.

## Data

Stored in a local SQLite file (`offerbench.db` by default, override via
`OFFERBENCH_DB_PATH`):

- `raw_posts` — every fetched post, deduped by `topic_id`, including full
  post content.
- `extracted_offers` — LLM-extracted structured fields per post, versioned
  by `extraction_version` so re-extraction never loses history.
- `current_offers` (view) — latest extraction per post; what the dashboard
  and any ad-hoc SQL lookups should query.

## Tests

```bash
uv run pytest
```
