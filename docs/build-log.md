# Build Log

## 2026-09-07/08 — Day 1 (steps 1–4 complete; step 5 code complete, full-corpus ingestion pending; step 6 pending)

### Commits this session

- `da88a3b` scaffold gateway skeleton with FastAPI health and proxy endpoints
- `47e0876` update skill path references from platform/ to finsentry/
- `d4e3b7c` add Docker Compose stack with Redpanda, RisingWave, and Postgres
- `515f23e` pin Redpanda and RisingWave to specific version tags
- `d70d505` add day 1 build log and correct docs paths
- `e546b07` ingest FinanceBench golden set into Postgres
- `e98605d` add migration runner tests

### Step 1 — Project scaffold and gateway skeleton (complete)

Created the `finsentry/` package with `finsentry/gateway/main.py`. FastAPI app exposes `GET /health` returning `{"status":"ok"}` and `POST /v1/chat/completions` as a transparent async proxy to a configurable `DOWNSTREAM_URL`. Added `pyproject.toml` (ruff, mypy strict, pytest), `requirements.txt`, and `.env.example`.

Package is named `finsentry`, not `platform`. Python's stdlib ships `platform.py` and any local package with that name shadows it, breaking `platform.python_version()` inside pytest's terminal reporter on collection. CLAUDE.md commands and `.claude/skills/` path references updated to match.

All checks pass: `ruff check .`, `mypy finsentry/`, `pytest -x -q`.

### Step 2 — Docker Compose stack (complete)

`docker-compose.dev.yml`: Postgres 16 on port 5432, Redpanda v26.2.2 (dev-container mode, `--smp 1`) on port 9092, RisingWave v3.0.3 (playground mode) on port 4566. All three services have healthchecks. All three show `(healthy)` in `docker compose ps` STATUS before any traffic.

Images are pinned to specific version tags. Versions confirmed from running containers: `rpk version` for Redpanda, `risingwave --version` for RisingWave.

Verified: `rpk cluster info` returns broker metadata, `SHOW TABLES` on RisingWave succeeds, `psql` to Postgres connects and runs `\dt`.

**Known issue.** RisingWave v3.0.3 in playground mode crashes after roughly five hours. The meta service deletes the worker registration on a heartbeat timeout, and the frontend loses contact. Container recovers on a fresh restart. Watch for this on Day 4 when the streaming worker pool runs continuously.

### Step 3 — FinanceBench golden set ingestion (complete)

Postgres driver changed from psycopg2-binary to `psycopg[binary]` (v3) to get native async support for Day 4. psycopg v3 puts `executemany` on `Cursor`, not on `Connection` — mypy caught this immediately.

`finsentry/db/migrate.py`: numbered SQL migration runner. Creates a `schema_migrations` table (filename TEXT PRIMARY KEY, applied_at TIMESTAMPTZ). For each `.sql` file in `finsentry/db/migrations/` in lexicographic order: checks if already applied, skips if so, otherwise runs inside a transaction and records the filename on success. Transaction rolls back cleanly on failure, no row written.

`finsentry/db/migrations/001_golden_set.sql`: creates `golden_set` (id TEXT PK, question TEXT, expected_answer TEXT, doc_id TEXT, source TEXT DEFAULT 'financebench', created_at TIMESTAMPTZ DEFAULT now()).

`finsentry/ingestion/financebench.py`: loads `PatronusAI/financebench` (train split, 150 rows) from HuggingFace without auth. Field mapping: `financebench_id` to `id`, `question` to `question`, `answer` to `expected_answer`, `doc_name` to `doc_id`. Bulk insert with `ON CONFLICT (id) DO NOTHING`.

`tests/db/test_migrate.py`: three cases using `tmp_path` and `patch.object(migrate, "MIGRATIONS_DIR", tmp_path)`. First run applies migration and records it. Second run skips it. Bad SQL rolls back with no row in `schema_migrations`. Autouse fixture cleans up test-specific rows after each case.

`tests/ingestion/test_financebench.py`: row count = 150, schema column names match, idempotency (second ingest leaves count unchanged).

`SELECT COUNT(*) FROM golden_set` returns 150. `\d golden_set` shows six expected columns. All 8 pytest tests green.

### Step 4 — FinQA-hallucination-detection ingestion (complete)

**Dataset path resolution.** The spec references "Sardana" as the author, but no dataset with that owner exists on the Hub. Hub search for "FinQA hallucination" returned three results:

- `Cleanlab/FinQA-hallucination-detection` — 1657 rows, single train split
- `wandb/finqa-data-processed-hallucination` — 13 248 train + 3 314 test rows (16 562 total)
- `kankshith123/FinQA-hallucination-detection` — 1657 rows, identical schema to Cleanlab (a mirror)

**Chosen dataset: `Cleanlab/FinQA-hallucination-detection`** (1657 rows). Reasons: the dataset explicitly contains GPT-4o responses (`llm_response` column), which matches the spec phrase "GPT-4o responses to FinQA questions along with binary correctness annotations." The wandb dataset does not name its model. Cleanlab is the community-standard reference for this benchmark. The 1657-row size fits a calibration benchmark better than 16k rows.

**Spec correction note.** The spec says "Sardana published it." Cleanlab is the HuggingFace publisher of record. We will correct `docs/internal/Project4_Description.docx` on a later cleanup pass. No code change needed — the ingestion script references the dataset by its Hub path.

**Cleanlab dataset schema.**

| Column | Type |
|---|---|
| `query` | string |
| `context` | string |
| `llm_response` | string |
| `is_correct` | int64 (0 or 1) |

No `id` column exists in the source.

**Confirmed field mapping to `hallucination_bench`.**

| Our column | Source | Note |
|---|---|---|
| `id` | `sha256(query + llm_response).hexdigest()[:16]` | Content hash, stable across re-ingestions |
| `question` | `query` | |
| `context` | `context` | |
| `response` | `llm_response` | |
| `is_hallucination` | `not bool(is_correct)` | Inverted: `is_correct=0` means hallucination |
| `source` | `'finqa-halluc'` | constant |
| `created_at` | `DEFAULT now()` | |

**Implementation notes.**

Migration `002_hallucination_bench.sql` creates the seven-column table. `finqa_hallucination.py` maps fields inline: `id = sha256(query + llm_response).hexdigest()[:16]`, `is_hallucination = (is_correct == 0)`. Three tests pass: row count, schema names and types via `information_schema.columns`, idempotency.

**Source deduplication finding.** The dataset has 1657 rows but six pairs share identical `(query, llm_response, is_correct)` — genuine duplicate records with agreeing labels. `ON CONFLICT DO NOTHING` correctly collapses them to 1651 unique rows. Test assertions reflect 1651.

`SELECT COUNT(*) FROM hallucination_bench` returns 1651. `\d hallucination_bench` shows seven columns. `ruff check .`, `mypy finsentry/`, and `pytest -x -q` (11 tests) all pass. Commit `d70f5df`.

**Next: Step 5** — SEC EDGAR filing ingestion for ten companies (AAPL, MSFT, NVDA, GOOGL, META, AMZN, JPM, BRK-B, TSLA, WMT). Requires `edgartools` and `EDGAR_IDENTITY="fin-sentry noreply@fin-sentry.local"` in `.env`.

**Day 11 README reminder.** The Day 11 setup section must include `psql ... -c "CREATE DATABASE finsentry_test;"` (or `createdb finsentry_test` if the user's PATH includes the Postgres bin directory). Tests will fail on a fresh clone without it.
