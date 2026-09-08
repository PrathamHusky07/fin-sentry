# Build Log

## 2026-09-07 — Day 1 (partial: steps 1, 2, and 3 of 6 complete; step 4 probe complete, implementation pending)

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

### Step 4 — FinQA-hallucination-detection ingestion (probe complete, implementation pending)

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

**What remains for step 4.**

1. Write `finsentry/db/migrations/002_hallucination_bench.sql` with the seven-column schema above.
2. Write `finsentry/ingestion/finqa_hallucination.py` using the confirmed mapping, psycopg v3, `ON CONFLICT (id) DO NOTHING`.
3. Write `tests/ingestion/test_finqa_hallucination.py`: row count = 1657, schema column names and types via `information_schema.columns`, idempotency.
4. Verify: `SELECT COUNT(*) FROM hallucination_bench` = 1657, `\d hallucination_bench` shows seven columns, `ruff check .` and `mypy finsentry/` clean, `pytest -x -q` green.
5. Commit as one logical unit.

**Open questions and things to watch.**

- The `sha256` import is from stdlib `hashlib` — no new dependency.
- `is_correct` is `int64` not `bool`, so the inversion is `is_correct == 0` (or `not bool(is_correct)`) — either works. Confirm which the ingestion script should use before writing.
- After step 4, two more Day 1 items remain: step 5 (SEC EDGAR filing ingestion for ten companies) and step 6 (verify coverage across all ten companies). Step 5 requires edgartools and the `EDGAR_IDENTITY` env var set to `"fin-sentry noreply@fin-sentry.local"`.
- The ten companies for EDGAR ingestion: Apple (AAPL), Microsoft (MSFT), Nvidia (NVDA), Alphabet (GOOGL), Meta (META), Amazon (AMZN), JPMorgan Chase (JPM), Berkshire Hathaway (BRK-B), Tesla (TSLA), Walmart (WMT).
- RisingWave playground heartbeat issue: if the container crashes during a long work session, restart it with `docker compose -f docker-compose.dev.yml restart risingwave`.
