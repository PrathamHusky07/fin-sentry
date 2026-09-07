---
name: judge-scoring
description: "Follow this pattern when adding or modifying a judge in either tier of the two-tier judge layer. Triggers on any work touching the flash tier (Gemini 2.5 Flash running the three RAGAS metrics with Zheng et al bias mitigations), the frontier tier ensemble (HHEM-2.1-open, Patronus Lynx 8B, Prometheus 2 7B running locally), the FaithJudge peer-example retrieval mechanism, or the ensemble normalization layer that turns three different output formats into a single verdict. Also triggers when modifying how judge scores are persisted, how the async worker pool consumes the stream, or how backpressure adjusts the frontier sampling rate."
---

# Judge scoring pattern

The two-tier judge layer is the most bias-prone part of the platform. Get the pattern wrong once and every downstream dashboard number is lying. Follow this exactly.

## Which tier does this belong in

Before writing code, know which tier the change is in.

**Flash tier** runs on one hundred percent of traffic. Gemini 2.5 Flash. The three RAGAS metrics only. Cheap, fast, biased in known ways that we mitigate. This is the tier the dashboard's real-time views read from.

**Frontier tier** runs on a sampled five to ten percent of traffic. Three local open-source models in an ensemble. HHEM-2.1-open for factual consistency. Patronus Lynx 8B for chain-of-thought faithfulness verdicts. Prometheus 2 7B for human-evaluation-trained scoring. This is the tier that calibrates the flash tier and is the target of the FaithJudge peer-example mechanism.

If a change spans both tiers, it is two changes. Do them separately.

## The three RAGAS metrics run in every flash judge

Every flash-tier judgment produces three scores. Never skip one.

**Faithfulness.** Decompose the response into individual claims. For each claim, ask the judge whether the retrieved context entailed it. Score is supported claims divided by total claims. Use the RAGAS prompt as published. Do not paraphrase the prompt.

**Answer Relevance.** Ask the judge to reverse-generate three questions that the response could plausibly be answering. Compute cosine similarity between each generated question and the original question using the same embedding model that the RAG endpoint uses for retrieval. Score is the mean similarity.

**Context Relevance.** Ask the judge to extract the sentences from the retrieved context that were essential to answering the question. Score is essential sentences divided by total retrieved sentences.

All three go into every trace event as separate fields. Do not compress them into a single "quality" score. The whole point of having three is that they measure different things.

## The four bias mitigations from Zheng et al

Every judge prompt in the flash tier implements all four mitigations. They are not optional. Every one has a documented effect size in the paper.

**Position swap for pairwise comparisons.** When the judge is asked to compare two responses, call it twice with the order reversed. If the two calls disagree on the winner, declare a tie. This is not the same as taking the majority of two calls. Disagreement means the judge is position-sensitive on this pair, and the honest verdict is that we cannot tell.

**Chain-of-thought prompt for math and reasoning.** When the question involves numeric reasoning or arithmetic, use the CoT judge prompt from the paper's appendix. The paper shows this cuts the failure rate on math questions in half. Detect math questions by the presence of digits, percent signs, currency symbols, or arithmetic operators in the question, and by the FinQA classifier if available.

**Reference-guided prompt when a golden answer exists.** When the request corresponds to a FinanceBench question with a human-verified answer, use the reference-guided prompt. The paper shows this cuts the failure rate in half again on top of the CoT gain.

**Explicit output format.** Every judge prompt ends with an explicit output schema specification. The judge outputs JSON with named fields. No free text. This is not a bias mitigation from the paper directly, but it is the pattern that makes bias mitigation observable, because we can log what the judge said before it was parsed.

Every mitigation has a corresponding field on the trace event so we can measure how often it fired and what effect it had. `judge.cot_used`, `judge.reference_used`, `judge.position_swap_disagreed`.

## The FaithJudge peer-example mechanism

The frontier tier implements FaithJudge from the Vectara benchmarking paper. This is what pushes agreement with human judgment substantially above zero-shot.

For each sampled response, the platform retrieves K peer examples from the FinanceBench and FinQA golden sets. Peers are structurally similar to the current query, meaning they hit similar filings, similar question types, and similar answer shapes. Pick K equal to three by default. Peers include the question, the retrieved context, the response, and the human verdict.

Inject the peers into the frontier judge prompt as few-shot examples with the pattern the paper describes. Never modify the peers on the fly. If the peer set for a query is empty because no structurally similar examples exist, fall back to zero-shot and log `judge.faithjudge_fallback_reason: no_peers`.

The peer retrieval is a separate module. It lives at `finsentry/judges/faithjudge_retrieval.py`. Test it independently of any judge.

## The ensemble normalization contract

The three frontier models emit different output shapes. The normalization layer turns them into one verdict.

HHEM-2.1-open outputs a probability between zero and one. Lynx outputs a `PASS` or `FAIL` string with a reasoning field. Prometheus 2 outputs a numeric score from one to five.

The normalization layer produces four fields on the trace event.

**`ensemble.verdict`** is one of `pass`, `fail`, or `dissent`. Compute by first normalizing each model to a pass or fail. HHEM passes when probability is above 0.5. Lynx passes when it emits `PASS`. Prometheus passes when the score is above three. Verdict is `pass` when all three agree pass, `fail` when all three agree fail, `dissent` when they disagree.

**`ensemble.confidence`** is a number between zero and one that reflects how sharply the three agree. Compute as the fraction of models on the majority side. Three of three is 1.0, two of three is 0.667.

**`ensemble.per_model`** is a dictionary with the raw output from each model. Never lose the raw output. The dashboard renders it in the drill-down modal and interviewers ask about it.

**`ensemble.disagreement_reason`** is populated only when `verdict` is `dissent`. It is a short string describing which model dissented and against what. Do not overthink the phrasing. `HHEM disagreed with Lynx and Prometheus. HHEM said fail, others said pass.` is enough.

Every judge score, tier, and ensemble field goes into the trace event and is persisted to Postgres. The MCP server's `get_judge_scores` tool returns all of them for a given request ID.

## Async worker pool and backpressure

Judges run asynchronously after the gateway response has returned to the caller. The worker pool consumes from the Redpanda `gateway.events` topic and produces to `judge.events`. Flash workers process every event. Frontier workers process the sampled subset.

When the frontier worker backlog exceeds a threshold, the sampling rate for the frontier tier is automatically reduced. Threshold is one thousand pending events by default. Sampling rate can drop from ten percent to one percent under load. When the backlog clears, the rate returns to normal. Log every rate change with a reason.

Do not implement this as a shared mutable variable everyone reads. Implement it as a small controller that publishes a `frontier.sampling_rate` value to a dedicated topic. The workers read from that topic and adjust. This makes the behavior visible in the dashboard and testable in isolation.

## Verification checklist before you say a judge change is done

1. Unit tests pass for the specific judge or ensemble change.
2. A live traffic run produces judge scores in the trace event with all expected fields populated.
3. For flash tier changes, the trace event shows the correct mitigation flags (`cot_used`, `reference_used`, `position_swap_disagreed`).
4. For frontier tier changes, the trace event shows all three model outputs in `ensemble.per_model` and the correct verdict.
5. For FaithJudge changes, the trace event shows either the peers used or the fallback reason.
6. The dashboard's Judge Panel modal renders the change correctly.
7. The MCP server's `get_judge_scores` tool returns the change correctly.
8. If the change affects the calibration harness, the Cohen's kappa recomputation on a small holdout produces a sensible number.

Any of these failing means the change is not done.
