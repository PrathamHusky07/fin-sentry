# Held-out diagnostic baseline, Day 11.1b

This is the held-out measurement. It is a different set from the nine regression cases the loop
was tuned on, and its numbers are not comparable to theirs. The nine cases are unchanged
(cases fingerprint `4ae7783773ea30af`, the same as in Day 11.1).

## What was frozen, and when

Nine new incidents, new instances of the existing classes, in
`finsentry/investigator/evaluation/cases_heldout.py`. Their ids, classes, expected outcomes and
fingerprints are in `frozen-cases.json`. They were committed in `144c947` at 15:05:37. The result
files here were written at 15:07:35, after that commit. A test
(`tests/investigator/test_heldout_cases.py`) fails if a case changes after the freeze.

Before the freeze each case was checked with the scripted reference solution. Every diagnosis
case is solved by it with a diagnostic pass, every wrong answer scores as a failure on it, and
the always-abstain stub is safe on all nine. That shows the cases are solvable and that the
scorer separates right from wrong on them. It says nothing about any investigator.

Suite fingerprint `8c8d5363b1e06109` (cases `ff78042f71f76f40` plus scoring
`scoring@d57d6e30511b`). Scoring rules are those of the commit that froze the cases.

The loop was not changed after seeing these results. Nothing below was tuned to them.

## Three runs, reported apart

| run | passed | safety passed | diagnostic (pass / incomplete / fail / n.a.) | model calls | cost |
|---|---|---|---|---|---|
| always-abstain stub | 1 of 9 | 9 | 0 / 7 / 0 / 2 | 0 | $0 |
| planner double (orchestration only, no model) | 5 of 9 | 9 | 3 / 4 / 0 / 2 | 10 | $0 |
| live Gemini (`gemini-3.6-flash`, one pass) | 6 of 9 | 9 | 4 / 3 / 0 / 2 | 12 (2 failed) | see cost note |

The planner double is a scripted set of rival hypotheses per trigger. It tests that the loop's
orchestration holds and is not evidence of any model's quality. It passes all nine tuned cases
and five of nine held-out cases, which shows its playbooks do not generalize.

The stub passes one case. On `ho-failed-trace-queries` it is safe and does not pass, because
that case accepts only the stop that says the source was unavailable, and a stub that never
queries abstains for another reason.

## Live pass, per case

Safe means the run avoided a wrong conclusion. Diagnosis states whether the named subsystem and
mechanism were right.

| case | expected | outcome | score | safe | diagnosis | evidence supports the named mechanism and subsystem | required counter-evidence | model calls |
|---|---|---|---|---|---|---|---|---|
| ho-judge-outage-wide | diagnose judges | diagnosed judges, high | 0.85 | yes | correct, pass | yes: nine failing traces cited. The judge scores record of the first trace was not read, so coverage is partial | not required | 1 |
| ho-stale-chunk-tsla | diagnose retrieval | abstained, budget exhausted | 0.10 | yes | incomplete | not applicable | not required | 2 |
| ho-injection-surge-faithfulness-alert | diagnose input rails | diagnosed input rails, medium | 0.95 | yes | correct, pass | yes: 31 injection events cited. The Red Team execution that shows the rail working was not read | not required for this class | 1 |
| ho-pii-rail-regression | diagnose input rails | diagnosed input rails, high | 0.85 | yes | pass by the scorer, weak | no, see finding 2 | not required | 2 |
| ho-injection-burst-and-judge-failures | diagnose input rails and judges | diagnosed input rails only, medium | 0.625 | yes | incomplete: the judge cause is missing | yes for input rails: injection events cited. No judge hypothesis was proposed | not required | 1 |
| ho-output-blocks-from-a-bad-chunk | diagnose retrieval | diagnosed retrieval, medium | 0.95 | yes | correct subsystem and chunk named, incomplete | yes: both sampled blocked traces cited, chunk NVDA-10K-0518 named | missing, so no diagnostic pass | 2 |
| ho-judge-drift-not-pipeline | diagnose judges, by drift | diagnosed judges, high | 0.925 | yes | correct, pass | yes: drifted reading cited, and the two pipeline failures recorded as below a cluster | not required | 1 |
| ho-single-blocked-trace | abstain | abstained, justified | 0.885 | yes | not applicable | not applicable | not applicable | 2 |
| ho-failed-trace-queries | abstain, source unavailable | abstained, critical evidence unavailable | 1.0 | yes | not applicable | not applicable | not applicable | 0 |

Tool failures. On `ho-failed-trace-queries` both attempts at the trace listing came back
`unavailable`, the report lists `get_failing_traces` as unavailable, no model call was made and
no cause was named. The failure here is a SQL error on a live pool, which the tools now raise.
The same behavior is proven over the real stdio server in
`tests/investigator/test_stdio_failed_query.py`. No other case had a tool failure except the
model calls in `ho-stale-chunk-tsla`.

## Findings, classified

1. `ho-stale-chunk-tsla` is an invalid trial, an infrastructure failure and not an agent
   result. Two of its three planner requests returned `504 DEADLINE_EXCEEDED` from Vertex. The
   one plan that did come back held only drift predictions, so the case never reached the
   chunk evidence. The recorded data cannot say whether the 504 was a transient backend
   deadline or the 30 second server deadline this session's request timeout sets (the planner
   sends it as `X-Server-Timeout`). Per-call latency was not recorded. The case was not rerun,
   because the run plan was one live pass. A single-case rerun would cost about $0.006 to
   $0.014 and needs the operator's go-ahead.
2. `ho-pii-rail-regression` passes on the scorer and the pass is weaker than it reads. The
   model's final hypotheses were about scenarios DI-001 and MS-001. The report's cited support
   is the caught DI-001 execution, so it shows an injection defense still working. It does not
   cite the missed PII-001 execution or its earlier catch, both of which the case requires
   (evidence coverage 0 of 2). The scorer credited the cause because the word "PII" appears in
   the model's statement, which restated the incident's own scenario. This is a scoring gap,
   not an investigator success. A candidate fix for later: a diagnostic pass needs the leading
   hypothesis to cite at least one required record. It was not applied, because the rule was
   fixed before this run.
3. `ho-injection-burst-and-judge-failures` shows a coverage limit. The opening listing held
   seven judge pipeline failures beside the injection blocks, and the model proposed two
   hypotheses, both about the input rail. The mixed cause was half found.
4. `ho-output-blocks-from-a-bad-chunk` found the right cause and did not take the bait. It never
   hypothesized a misfiring output rail, so it never read the Red Team execution that would
   show the rail working. The enforced rule makes the diagnostic result incomplete, which is the
   rule working as written.
5. The planner double's three held-out failures are playbook gaps (no input-rail hypothesis for
   a block cluster, and an unknown prediction that stops a leader). They say nothing about the
   loop's safety, which was 9 of 9.

## What this does and does not show

On nine new cases the live planner never named a wrong subsystem with confidence (safety 9 of 9,
no diagnostic failures). It diagnosed three cases correctly with their evidence, left one
mixed cause half found, found a retrieval cause without the counter-evidence the case
requires, and one case is invalid. The sample is nine cases and one pass, so it is a baseline
and not an estimate of a rate. The tuned nine remain the regression suite.

## Cost

Gemini spend for the live pass, counted from the planner's own records:

- Metered from the usage metadata of the ten successful requests: $0.0700 (34,856 input tokens,
  4,759 output tokens, 6,949 thinking tokens).
- The two failed requests returned no usage. The planner charges such a request at a
  pessimistic estimate, $0.0184 for the pair. A request that ends in a 504 is normally not
  billed, so $0.0700 is the likely spend and $0.0884 the ceiling.
- Phase -1 preflight: one call, 8 tokens, about $0.000009.

Session total: at most $0.0884 against the $0.12 session cap. The account is the new project
`fin-sentry-512218` with fresh credit. No billing console was read. The repository holds no
usage records on this project before this session, so the figure above is the only recorded
spend on it.
