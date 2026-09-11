# ADR 005: Output Rail Architecture

**Date:** 2026-09-10
**Status:** Accepted

## Context

Day 3 of the build plan requires three output rails running post-generation on the
(response, context) pair before the answer reaches the caller. The spec (lines 144-156)
defines them as: (1) schema enforcement, (2) regulated-phrase blocklist, and (3)
reference-free RAGAS Faithfulness.

Two library choices required substitution due to the zero-cost constraint.

**Guardrails AI 0.11.0** was evaluated. Its `pip install guardrails-ai --dry-run` resolves
`openai<3.0,>=2.0` and `litellm>=1.82.5` as non-optional transitive dependencies. litellm
itself pulls boto3. These are paid-API clients. The installation violates the project
constraint at `pyproject.toml` level, not just at runtime.

**ragas 0.4.3** was evaluated. Its `pip install ragas --dry-run` resolves `openai>=1.0.0`
and `langchain_openai` as non-optional transitive dependencies. The ragas library has no
Gemini-native LLM backend abstraction. The Es et al. 2023 Faithfulness algorithm is
public; implementing it directly against the already-installed `google-genai` SDK is
straightforward and avoids the prohibited dependencies.

**Gemini model**: The spec references `gemini-2.5-flash`. Google has gated 2.5 Flash
away from new API consumers on the Developer API path and redirects them to
`gemini-3.6-flash`. This substitution is documented here. The session prompt confirms the
user verified `gemini-3.6-flash` responds via `google-genai` with no billing card required.
All production code uses `GEMINI_MODEL=gemini-3.6-flash` from `.env`. Do not silently
switch models if a 404 fires; stop and report.

## Decision

### Response contract (RagAnswerResponse)

The downstream LLM now receives a system prompt instructing structured JSON output:

```json
{
  "answer": "...",
  "citations": [{"chunk_id": "...", "quote": "..."}],
  "confidence": "low|medium|high"
}
```

`citations` carries no minimum length constraint. An answer with no supporting evidence
must return `citations=[]` and `confidence="low"`. The model may not invent chunk_ids;
it may only cite ids present in the `[chunk_id=...]` labels in the user message.

`RagQueryResponse.answer` is now typed as `RagAnswerResponse` (was `str`). This is a
client-facing contract change. Callers that relied on `answer` being a plain string must
update to `answer.answer`.

### Output rail status code

Output rail blocks return HTTP 422 (Unprocessable Entity) with body
`{"error": "output_rail_block", "rail": ..., "reason": ..., "details": {...}}`.

ADR 004 uses 403 for input rail blocks. Output rail blocks are semantically different:
the request was valid and the downstream processed it; the gateway is withholding the
result because it failed post-generation validation. 422 does not conflict with any code
in ADR 004's taxonomy (which uses 403, 429, 502, 503, 504 for other conditions).

### Rail A: Schema enforcement (pure Pydantic, fallback for Guardrails AI)

`SchemaEnforcementRail` validates the downstream's response string using pure Pydantic
(`RagAnswerResponse.model_validate(json.loads(response_text))`). This is the functional
equivalent of Guardrails AI's `Guard.validate` for this schema. The interface is
intentionally similar: a single `.check(response_text, retrieved_chunk_ids)` method
returning a typed `RailDecision`.

Behavior sequence (first block wins):
1. JSON parse failure: block `malformed_json`
2. Pydantic validation failure: block `schema_violation`
3. Citation chunk_id not in retrieved set: block `hallucinated_citation`
4. Empty citations with confidence != "low": block `empty_citations_with_non_low_confidence`
5. Pass: `details["parsed"]` carries the `RagAnswerResponse` instance

### Citation cross-check as primary metadata-tampering defense

`source_trust.check_chunk` validates each chunk's `ticker`, `filing_type`,
`filing_date`, `source_url`, and `chunk_id` independently. It does NOT cross-validate
the complete (ticker, filing_type, filing_date, source_url) tuple against the canonical
corpus row for that `chunk_id`. Per the source-trust Task A finding documented in the
Stage 1.5 build log, this is safe in the current production path because `RetrievedChunk`
is built from a single SQL `corpus` row: the metadata fields and chunk_id originate from
the same record, so they cannot be decoupled by the retrieval path alone.

However, this means source-trust does NOT defend against a threat model where a chunk_id
and its metadata become decoupled after retrieval (e.g., by a prompt-injected rewrite of
the context assembly, or by a future retrieval path that merges metadata from multiple
sources). The citation cross-check in `SchemaEnforcementRail` IS the primary defense
against this threat model: it verifies that every chunk_id the model cites was actually
present in the filtered retrieval set. A response that cites a chunk_id not in that set
is blocked regardless of how the id was introduced.

This is defense at the generation boundary, not defense-in-depth via independent checks.
Future work: add tuple cross-validation to source-trust to close the gap.

### Rail B: Regulated-phrase blocklist

`RegulatedPhraseRail` scans `RagAnswerResponse.answer` (not citation quotes) against six
compiled regex patterns covering FINRA Rule 2210 and SEC Rule 156 prohibited language.
Word-boundary anchors prevent false positives on partial matches.

The rail runs on the answer field only, not on citation quotes, because the model may
legitimately quote SEC filings that contain regulated language in a disclosure context
(a fraud complaint may reference "guaranteed returns"). Quoting is not asserting.
The distinction is enforced architecturally: the rail receives `parsed_answer.answer`
as a string, not the raw JSON response.

### Rail C: Faithfulness (our implementation of Es et al. 2023, via Gemini)

`FaithfulnessRail` implements the reference-free Faithfulness metric from the RAGAS
paper (Es et al. 2023) directly using the `google-genai` SDK. This is our own
implementation, not the `ragas` PyPI package. The algorithm is:

1. Claim extraction: prompt Gemini to extract atomic factual claims from the answer.
   Capped at 10 claims to bound cost on adversarial long answers.
2. Per-claim NLI: for each claim, prompt Gemini to verify against the retrieved context.
3. Score: `supported_claims / total_claims`. Score = 1.0 when no claims (RAGAS convention).
4. Threshold: block if `score < threshold` (provisional 0.7; Day 6 calibrates against
   FinanceBench with Cohen's kappa).

Context sent to Gemini is assembled from `filtered_chunks` (the retrieval-rail output),
not from the raw retrieval candidates. This ensures Faithfulness runs only on the context
the model actually saw, which is the correct evaluation surface.

Faithfulness metadata (score, claims, Gemini usage) goes in `output_rail_trace`, not in
the client-facing `answer` object. Client-facing shape is unchanged: `{answer, citations,
confidence}`. `output_rail_trace` is a peer field on `RagQueryResponse`.

### Failure policy for FaithfulnessRail

The fail-open policy is per-error-type, listed in the implementation docstring.
`config/rails.yml` carries `output.faithfulness.on_failure: open` to document this.

The rationale for fail-open (vs. the closed default for input rails): Faithfulness uses
an external API (Gemini) with independent availability, rate limits, and latency variance.
An input rail failing closed on a transient Gemini error would cause 503 storms on a
production gateway that is otherwise fully healthy. The input rails (Prompt Guard,
Presidio, Llama Guard) run locally with no external dependencies; their fail-closed
default is correct. Faithfulness is different in kind.

### Latency accounting

Adding to ADR 004's pre-downstream accounting: the output rails add post-generation
latency. Schema enforcement and regulated-phrase rail are in-process and negligible
(<1ms each). Faithfulness adds (1 + N) Gemini API calls where N = number of claims
extracted (capped at 10). On the Gemini Developer API free tier with `gemini-3.6-flash`,
each call is approximately 10-30 seconds. `gemini-3.6-flash` is a thinking model that
internally allocates thought tokens before producing visible output, which dominates
per-call latency. Empirical measurement in this environment: ~23-24 seconds per call.

A response with 5 claims incurs approximately 120-150 seconds of additional post-generation
latency in the worst case. The per-call timeout is 30 seconds; the total budget is 120
seconds (accommodating claim extraction + up to 3 claim verifications before budget
expiry).

This is a known trade-off. Faithfulness runs synchronously in the request path at Day 3
because the async judge worker pool (Day 4) is not yet implemented. Day 4 moves
faithfulness to the async evaluation path so it no longer blocks the response. Until
then, the 120-second faithfulness total budget is the documented ceiling.

## Alternatives Considered

**min_length=1 citation constraint**: Considered requiring at least one citation on every
response (rejecting empty citations unconditionally). Rejected. A legitimate abstention
("the retrieved context does not answer this question") should return empty citations.
Forcing a citation would either produce hallucinated references or suppress valid
abstentions. The self-consistency check (empty citations -> confidence "low") is the
correct constraint: it verifies the model's own certainty signal is coherent.

**Fail-closed Faithfulness**: Considered defaulting Faithfulness to fail-closed. Rejected.
The Gemini Developer API is subject to rate limits (15 RPM on the free tier), and a
production gateway under moderate load would hit these limits and reject valid requests
with 503. Fail-open preserves gateway availability at the cost of unchecked faithfulness
on those responses; this is the correct priority ordering for a reliability platform that
must itself be reliable.

**Pydantic strict mode**: Considered using `model_config = ConfigDict(strict=True)` on
`RagAnswerResponse`. Rejected for now. Strict mode would reject numeric `confidence`
values from a model that occasionally formats numbers instead of strings, producing
opaque errors. The current Literal constraint with Pydantic's default coercion catches
invalid values while tolerating minor type variance.

## Consequences

- `RagQueryResponse.answer` is now `RagAnswerResponse`, breaking any caller that reads
  `answer` as a plain string. ADR 004 did not define the answer type normatively; this
  is the first normative definition.
- Output rail blocks return 422. Callers must handle 422 in addition to the codes
  documented in ADR 004.
- Faithfulness adds post-generation latency. Total request time can approach 37 seconds.
  Day 4 moves Faithfulness to async to restore the sub-30s window.
- The `ragas` and `guardrails-ai` packages are NOT installed. The project's dependency
  tree has no openai, litellm, or langchain-openai packages.
- `google-genai>=2.22.0` is the only new production dependency added by Session C.

### Vertex AI migration and zero-cost architecture (2026-09-11)

Migration from the Gemini Developer API (rate-limited free tier, ~1500 RPD ceiling on
fresh projects, prompts and responses used for model improvement) to Vertex AI on Google
Cloud (`aiplatform.googleapis.com`). Authentication via Application Default Credentials,
not an API key.

**Project:** dedicated GCP project `fin-sentry` with billing enabled. The billing account
holds the $300 Google Cloud Free Trial credit.

**Zero-cost architecture:** the $300 credit is a hard ceiling, not a budget to consume.
Per-call ($0.02), per-run ($5), per-day ($25) dollar ceilings are enforced in
`CostBudget` (`finsentry/rails/output/cost_governance.py`). `FaithfulnessRail` calls
`CostBudget.can_proceed()` before every Gemini call; if any ceiling would be exceeded,
the rail raises `_GeminiSkipError("skipped_budget", ...)` and fails open.

**Empirical validation:** the user verified a single Gemini smoke test call returned
`Response: OK` with `usage_metadata` showing thinking tokens present
(`thoughts_token_count=90` for a trivial prompt). This confirms thinking tokens must
be first-class in cost accounting. Vertex-mode smoke test with `gemini-3.6-flash` and
two synthetic pairs (Pair A: faithful; Pair B: unfaithful):

- Pair A: score 1.0, PASS. 5 Gemini calls, 747 input / 290 output / 1506 thinking tokens.
- Pair B: score 0.0, blocked. 6 Gemini calls, 748 input / 329 output / 2095 thinking tokens.
- Total cost: $0.016946 against $25 per-day ceiling.

**Data policy:** Vertex enterprise governance means prompts and responses are NOT used for
model training without explicit permission. Correct posture for financial data even though
the demo corpus is public SEC filings.

**Pricing:** `gemini-3.6-flash` on Vertex Standard tier: $0.75/M input tokens, $3.75/M
output tokens (through Dec 31, 2026). Thinking tokens are billed at the output rate.
Batch/Flex tier: $0.375/M input, $1.875/M output. Reserved for Day 6 FinanceBench
calibration.

**Day 6 FinanceBench projection:** approximately 2250 Gemini calls (150 queries times
~15 calls per Faithfulness check). Projected Standard cost ~$0.76; Batch/Flex ~$0.38.
Both are well under the $300 credit and below the per-day $25 ceiling when spread across
two days or run as one Batch job.

**Pending acceptance criterion:** the user should inspect Google Cloud Console, Billing,
Reports approximately 24 hours after this session to confirm Vertex AI SKU line items
appear for `gemini-3.6-flash` and that a matching credit offset brings the net charge to
zero. Until confirmed, the zero-cost claim is validated by pricing documentation and code
enforcement, but not yet by billing reality.
