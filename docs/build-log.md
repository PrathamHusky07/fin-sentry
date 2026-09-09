# Build Log

## 2026-09-08 — Day 2 remediation: Colang migration preflight (session handoff)

### What was done this session

**Python 3.13 downgrade (commit `33dfeff`).** The Phase 1 diagnostic revealed NeMo Guardrails was silently failing to initialize on Python 3.14 (`'function' object is not subscriptable` from the Colang v1.0 runtime importing LangChain code). Dropped to Python 3.13.14 via `uv venv --python 3.13`. Updated `pyproject.toml`: `requires-python = ">=3.13,<3.14"`, `ruff target-version = "py313"`, `mypy python_version = "3.13"`. One ruff auto-fix from the py313 target: `AsyncGenerator[T, None]` simplified to `AsyncGenerator[T]` in [finsentry/gateway/main.py](finsentry/gateway/main.py). 41/41 tests pass, ruff and mypy clean. `nemoguardrails 0.24.0` resolved by uv (up from `>=0.10.0` lower bound), `transformers 5.16.1`.

**NeMo diagnostic on Python 3.13.** Re-ran `scripts/diagnostic_nemo.py`. NeMo now initializes: `adapter._nemo` is an `LLMRails` instance, not `None`. The `explain()` call returns `ExplainInfo(llm_calls=[], colang_history=None)` — both fields are empty because the current adapter bypasses Colang completely, routing requests via `asyncio.to_thread(rail.check, ...)` directly. NeMo records nothing when its flow engine is not invoked. The `runtime.registered_actions` catalog is live and queryable; `dict(nemo.runtime.registered_actions)` returns all 60+ built-in actions plus our registered `diag-rail.check`.

**Decision: adopt Colang.** The spec (Component One, line 158) states "The entire rail stack runs behind NeMo Guardrails, which orchestrates the sequencing and provides a single audit surface." The current adapter makes that false. The fix is to route requests through NeMo's `check_async()` so NeMo owns sequencing and `explain()` fills with real data.

**Nine-point Colang migration plan produced.** Full plan written and agreed in conversation. Key findings from API inspection during planning:

- `nemo.check_async(messages, rail_types=[RailType.INPUT])` is the correct entry point for input rails. Returns `RailsResult(status: RailStatus, content: str, rail: Optional[str])` where `status` is one of `PASSED`, `MODIFIED`, `BLOCKED`.
- NeMo 0.24.0 has a first-class `RailOutcome` API: `RailOutcome.allow()`, `RailOutcome.block()`, `RailOutcome.transform([(TransformTarget.USER_MESSAGE, text)])`, `RailOutcome.failure()`. This is the return type for registered action functions. It maps cleanly to our `RailDecision` (pass/block/sanitize/error).
- `TransformTarget.USER_MESSAGE` is the target for PII redaction — NeMo rewrites the in-flight user message to the sanitized text and `RailsResult.content` carries the sanitized content.
- `colang_history` populates in `explain()` when requests flow through `check_async()` — confirmed empirically in Experiment 2 below.
- `SentenceTransformerEmbeddingModel` with engine name `"SentenceTransformers"` is a registered provider in NeMo 0.24.0. Model name is passed as `parameters.embedding_model`.
- `models: []` (no LLM) is valid and `check_async()` succeeds with it for pure action-based flows.

**Preflight diagnostic run (`scripts/diagnostic_nemo_preflight.py`).** Two experiments.

**Experiment 1 — Embedding provider load timing:**

```
Config A: explicit SentenceTransformers embedding provider
  bge-small cached before: True
  bge weight files before: ['model.safetensors']
  LLMRails(config_a) wall time: 0.067s
  bge-small cached after:  True
  bge weight files after:  ['model.safetensors']

Config B: embedding_search_provider omitted entirely
  bge-small cached before: True
  LLMRails(config_b) wall time: 0.039s
  bge-small cached after:  True
  bge weight files after:  ['model.safetensors']

Delta (A - B): 0.029s
```

**Experiment 2 — Colang flow with `models: []` and a pure Python action:**

```
Building RailsConfig...
  colang_version: 1.0
  rails.input.flows: ['check test']

Instantiating LLMRails...
  Caught 1 warning(s) during LLMRails():
    [DeprecationWarning] Use 'nim_base_url' instead. This field will be removed in a future version.

  Registered action 'test_action': <function ...test_action at 0x109324f40>

Calling check_async([{role:user, content:hi}], rail_types=[RailType.INPUT])...
  [test_action] called — returning RailOutcome.allow()
  Result: RailsResult(status=<RailStatus.PASSED: 'passed'>, content='hi', rail=None)
  result.status: <RailStatus.PASSED: 'passed'>
  result.content: 'hi'
  result.rail: None
  Caught 0 warning(s) during check_async():

  explain().llm_calls: []
  explain().colang_history: 'execute test_action\n# The result was RailOutcome(decision=<RailDecision.ALLOW:
    \'allow\'>, reason=\'preflight test\', metadata={\'source\': \'preflight\'}, transforms=(), failed=False)\nuser "hi"\n  "hi"\n'

  Logged warnings/errors during experiment:
Synchronous action `test_action` has been called.
```

**Two small findings from preflight:**

1. The `"Synchronous action 'test_action' has been called."` log message (WARNING level via `logging`, not `warnings.warn`) appeared because the test action was a plain synchronous `def`. Registered action wrappers for our three rails must be `async def` to avoid this warning. This is the `execute_async=True` flag on the `@action` decorator, or simply declaring the wrapper as `async def` — both suppress the warning.

2. `"Use 'nim_base_url' instead."` DeprecationWarning fires at `LLMRails()` construction time. It originates inside NeMo's jailbreak-detection library config and is non-actionable — no code we write triggers it. It will appear in test output (as it already does in the current test suite, per the 18 warnings reported by pytest after today's dependency upgrade).

**Still unresolved from Phase 1 diagnostics:** The Prompt Guard 2 and Llama Guard 3 model diagnostics (`scripts/diagnostic_prompt_guard.py`, `scripts/diagnostic_llama_guard.py`) have not been re-run. Both models require a HuggingFace access token and have not been downloaded. The corrected model identifier (`meta-llama/Llama-Prompt-Guard-2-86M`) has not been verified against the Hub. The label taxonomy and raw output format of both models remain empirically unknown. These are resolved in Commit F of the migration.

### Exact next task: Commit A of the Colang migration

**What Commit A delivers:**

1. New directory `finsentry/gateway/colang/` with two files:
   - `config.yml` — NeMo runtime config: `models: []`, `core.embedding_search_provider` set to SentenceTransformers with `BAAI/bge-small-en-v1.5`, `rails.input.flows` listing the three flow names (`"check prompt injection"`, `"check pii"`, `"check hazard taxonomy"`).
   - `config.co` — Three Colang v1.0 flows, one `execute action_name` statement each. Flow names match exactly what `config.yml` lists.

2. `requirements.txt` lower bound tightened to `nemoguardrails>=0.24.0` (the `RailOutcome` API does not exist in earlier versions).

3. Verification for Commit A: `python -c "from nemoguardrails import LLMRails, RailsConfig; ..."` instantiates without error. ruff and mypy clean. No Python source changes.

**Full migration commit sequence after A:**

- **Commit B** — Adapter rewrite: `finsentry/gateway/rails.py` becomes thin wrapper calling `check_async()`. Gateway route reads `RailsResult.status`. ruff + mypy clean.
- **Commit C** — Async rail action wrappers: three `async def` wrapper functions translating `RailDecision` → `RailOutcome` (including rich metadata from `details`), emitting OTel spans per rail, applying fail-open/fail-closed from `config/rails.yml`. Decorated with `@action(name=..., execute_async=True)` to suppress sync-action warning. Registered on the `LLMRails` instance.
- **Commit D** — Test suite rework: assertions updated from `decisions[0].outcome` to `RailsResult.status`/`.content`/`.rail`. Add assertion that `explain().colang_history` is non-None after `check_async()`. Cover pass/block/sanitize/error, sequencing (block cancels subsequent flows), fail-open/fail-closed. 41/41 (not slow) pass.
- **Commit E** — Model identifier fix: `_MODEL_ID = "meta-llama/Prompt-Guard-2-86M"` → `"meta-llama/Llama-Prompt-Guard-2-86M"` in `finsentry/rails/input/prompt_guard.py`. One-line change.
- **Commit F** — Diagnostic checkpoint: re-run `diagnostic_prompt_guard.py`, `diagnostic_llama_guard.py`, `diagnostic_nemo.py` with HF token in `.env` and `load_dotenv()` at top of each script. Paste full raw output verbatim. Stop. Wait for review before Phase 3 label-normalization work.

**Realistic budget:** 12 to 18 hours across 1.5 to 2 full sessions. Test suite rework (Commit D) is the long pole — NeMo runtime behavior with mocked actions through Colang flows has edge cases that require iterative debugging. Plan two full sessions.

**Spec updates made (outside this session's code commits):** `docs/internal/Project4_Description.docx` received two surgical edits: Component One's rail-stack sentence names Colang and ExplainInfo explicitly; Component Four's `explain_guardrail_decision` tool description names the `ExplainInfo + RailDecision` combination.

## 2026-09-08 — Day 2 (complete)

Three input rails behind NeMo Guardrails, cheapest-first sequencing, OTel spans per rail. 41/41 tests green (2 `@pytest.mark.slow` model-load tests require HuggingFace download and skipped in CI with `-m "not slow"`). ruff and mypy strict clean throughout.

### Commits

- `3120bb5` align guardrails skill with revised retrieval-rail semantics (retrieval rail = pre-generation injection/PII/source-trust checks on chunks; post-generation Faithfulness lives in output rails)
- `6a5b902` add rail adapter, OTel setup, and NeMo wiring for Day 2
- `4e905e6` add Prompt Guard 2 input rail for prompt injection detection
- `a100b46` add Presidio PII redaction input rail
- `191d2a0` add Llama Guard 3 8B input rail for hazard taxonomy classification

### Architecture

`InputRailsAdapter` in `finsentry/gateway/rails.py` owns all sequencing. Gateway route calls the adapter; adapter calls rails directly in order; NeMo instance is stored for future MCP audit surface on Day 7. Per-rail `on_failure` config in `config/rails.yml` controls fail-open vs. fail-closed behavior at runtime; all three rails default to fail-closed. OTel emits one span per rail with attributes `rail.name`, `rail.layer`, `rail.decision`, `rail.latency_ms` via `SimpleSpanProcessor` (not Batch, which triggers I/O-on-closed-file during pytest teardown).

### Rail 1 — Prompt Guard 2 86M

`meta-llama/Prompt-Guard-2-86M`, `text-classification` pipeline, fp32 on CPU (DeBERTa-v3 has numerical drift on some MPS builds). Threshold 0.5 on injection probability. Pipeline returns top-label score, not injection probability directly: when top label is BENIGN, `injection_prob = 1.0 - score`. Key bug found and fixed during implementation: storing `score` directly when top label is BENIGN gave `injection_prob = 0.99` for a clean query, which would block it. The correct value is `0.01`.

### Rail 2 — Presidio PII redaction

Five pattern recognizers only: US_SSN, CREDIT_CARD, EMAIL_ADDRESS, PHONE_NUMBER, US_BANK_NUMBER, IBAN_CODE. PERSON excluded: public figures in finance queries (executives, analysts) must not be redacted or RAG retrieval on the corpus breaks. This lets us use `en_core_web_sm` (~50 MB) instead of `en_core_web_lg` (~750 MB) since no NER is needed. Confidence threshold 0.7 (default is 0.5; raised to prevent false positives on CIK numbers and CUSIP codes). SSN context-word boosting: base pattern score 0.5, context words "ssn"/"social"/"security" boost to 0.85 -- tests must include a context word and must not use `123-45-6789` (Presidio's canonical invalidated sample). Outcome is `sanitize` (not `block`) -- the redacted text flows downstream. The adapter propagates sanitized content to subsequent rails.

### Rail 3 — Llama Guard 3 8B

`meta-llama/Llama-Guard-3-8B`, NF4 4-bit quantization via `BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4", bnb_4bit_compute_dtype=torch.float16)`, `device_map="auto"`. NF4 over int8: Day 5 adds three frontier judges; the memory budget (24 GB unified RAM) does not fit int8 for all five models. NF4 buys ~4 GB headroom at ~2 percentage point cost on Meta's hazard taxonomy eval, invisible for finance-domain traffic. Output parsing handles `"safe"` and `"unsafe\nS<N>"` formats; category defaults to `"unknown"` when the category line is absent. Decodes only newly generated tokens by slicing `output[0][input_ids.shape[-1]:]`.

### NeMo Python 3.14 incompatibility

NeMo 0.10.x imports LangChain's `Chain` class which uses `Optional[dict[str, Any]]` annotations that Python 3.14 cannot evaluate at import time (`TypeError: 'function' object is not subscriptable`). `_init_nemo()` wraps the import in try/except; adapter continues with `self._nemo = None` and logs a warning. `RailsConfig.from_content()` and `register_action()` actually succeed -- only the Colang runtime raises. Fix options: wait for NeMo to update, or pin Python to 3.12 for Day 7 MCP work.

### Day 3 plan

Reference RAG endpoint over the SEC EDGAR corpus, exposing the retrieval-generation boundary. Retrieval rail (indirect prompt injection detection on chunks, PII scan, source-trust checks). Output rails with Guardrails AI + RAGAS Faithfulness. Circuit breaker with 20-second timeout on RAG endpoint calls.

## 2026-09-07/08 — Day 1 (complete)

All five steps done. Step 1 (`da88a3b`): FastAPI gateway skeleton with health and proxy endpoints. Step 2 (`515f23e`): Docker Compose stack — Postgres, Redpanda v26.2.2, RisingWave v3.0.3, all pinned and healthy. Step 3 (`e546b07`): FinanceBench 150 rows into `golden_set`. Step 4 (`d70f5df`, `f01226a`, `6163b9e`): FinQA-hallucination-detection 1651 unique rows into `hallucination_bench` (1657 source rows, 6 exact-duplicate pairs correctly collapsed), with null-byte hash separator, `EXPECTED_RECORD_COUNT` constant, and tests isolated to `finsentry_test`. Step 5 (`5709435`, `0e8ae10`): SEC EDGAR corpus — 8,319 chunks across all ten tickers (AAPL 166/137/44, MSFT 251/343/44, NVDA 239/244/48, GOOGL 262/315/68, META 346/525/50, AMZN 210/289/51, JPM 1149/1581/57, BRK-B 436/400/54, TSLA 196/218/47, WMT 264/230/55; columns are 10-K/10-Q/8-K chunks) stored in pgvector with HNSW cosine index, bge-small-en-v1.5 384-dim embeddings. Pre-existing gateway test bug caught and fixed (`e08036d`): `load_dotenv()` at module top caused `DOWNSTREAM_URL` from `.env` to leak into tests. 14/14 pytest green, ruff and mypy clean throughout.

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

### Step 5 — SEC EDGAR corpus ingestion with pgvector (complete)

**Infrastructure changes.** Postgres image switched from `postgres:16` to `pgvector/pgvector:0.8.6-pg16` (pinned; digest matches the `:pg16` floating tag). Collation version mismatch warning from the image change resolved with `ALTER DATABASE ... REFRESH COLLATION VERSION`. mypy target bumped from 3.11 to 3.12 because numpy 2.x stubs use Python 3.12 `type` statement syntax. Dependencies added: `sentence-transformers`, `pgvector>=0.3.0`, `langchain-text-splitters`, `tiktoken`, `tenacity`.

**Migration 003.** Enables `vector` extension, creates `corpus` table (12 columns), btree index on `(ticker, filing_type)`, HNSW cosine-distance index on `embedding` (pgvector 0.8.6 supports HNSW).

**Ingestion script `sec_edgar.py`.** EDGAR_IDENTITY validated at `ingest()` entry. edgartools `Company.get_filings(form=type)[:N]` to slice per-type. `document.markdown()` for text with fallback to `document.text()`. `RecursiveCharacterTextSplitter` with cl100k_base at 800/100 tokens. bge-small-en-v1.5 embeddings in batches of 32 (model cached at module level). Content-hash id `sha256(ticker\x00accession\x00chunk_index)[:16]`. Inserts in batches of 500 with `ON CONFLICT DO NOTHING`. tenacity retry (3 attempts, exponential backoff) per filing download. `register_vector(conn)` called per connection for psycopg3 vector type mapping.

**Test database migration path.** `finsentry_test` receives migration 003 via the conftest session fixture on the next `pytest` run. No separate migration step needed.

**Pre-existing gateway test bug found and fixed (separate commit `e08036d`).** `main.py` calls `load_dotenv()` at module top, so tests importing the gateway picked up `DOWNSTREAM_URL` from `.env`. The without-downstream 503 test then tried to connect to `http://localhost:11434` instead of hitting the guard. Fixed by patching `_DOWNSTREAM_URL` to `""` inside the test.

**Full-corpus verification.** All ten tickers ingested, all three filing types, filing counts match spec (2 × 10-K, 4 × 10-Q, 20 × 8-K per ticker).

| ticker | 10-K chunks | 10-Q chunks | 8-K chunks |
|--------|-------------|-------------|------------|
| AAPL   | 166         | 137         | 44         |
| MSFT   | 251         | 343         | 44         |
| NVDA   | 239         | 244         | 48         |
| GOOGL  | 262         | 315         | 68         |
| META   | 346         | 525         | 50         |
| AMZN   | 210         | 289         | 51         |
| JPM    | 1149        | 1581        | 57         |
| BRK-B  | 436         | 400         | 54         |
| TSLA   | 196         | 218         | 47         |
| WMT    | 264         | 230         | 55         |

Total: **8,319 chunks**. JPMorgan and Berkshire are large filers — financial services 10-Ks and 10-Qs are far longer than tech filings. All chunks are in the 20-to-200 range per filing. `pytest -x -q` (14 tests) green. `ruff check .` and `mypy finsentry/` clean. Commits `5709435` (Step 5 code) and `e08036d` (gateway fix).

**Day 11 README reminder.** Setup section must include `psql ... -c "CREATE DATABASE finsentry_test;"`. Tests fail on a fresh clone without it.
