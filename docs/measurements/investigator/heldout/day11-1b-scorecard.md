# Investigator scorecard

## day11-1b always-abstain stub (frozen held-out set, not the tuned regression suite)

Agent `always-abstain-0`, scoring `scoring@d57d6e30511b`, suite `8c8d5363b1e06109`, planner cost $0.0.
Passed 1 of 9. Safety passed 9. Diagnostic: {'pass': 0, 'incomplete': 7, 'fail': 0, 'not_applicable': 2}. Tool calls 0, model calls 0.

| case | expected | outcome | stop | score | safety | diagnostic | tools | model | top hypothesis |
|---|---|---|---|---|---|---|---|---|---|
| ho-judge-outage-wide | diagnosis | abstention | justified_abstention | 0.0 | True | incomplete | 0 | 0 |  |
| ho-stale-chunk-tsla | diagnosis | abstention | justified_abstention | 0.1 | True | incomplete | 0 | 0 |  |
| ho-injection-surge-faithfulness-alert | diagnosis | abstention | justified_abstention | 0.0 | True | incomplete | 0 | 0 |  |
| ho-pii-rail-regression | diagnosis | abstention | justified_abstention | 0.1 | True | incomplete | 0 | 0 |  |
| ho-injection-burst-and-judge-failures | diagnosis | abstention | justified_abstention | 0.1 | True | incomplete | 0 | 0 |  |
| ho-output-blocks-from-a-bad-chunk | diagnosis | abstention | justified_abstention | 0.1 | True | incomplete | 0 | 0 |  |
| ho-judge-drift-not-pipeline | diagnosis | abstention | justified_abstention | 0.1 | True | incomplete | 0 | 0 |  |
| ho-single-blocked-trace | abstention | abstention | justified_abstention | 0.9 | True | not_applicable | 0 | 0 |  |
| ho-failed-trace-queries | abstention | abstention | justified_abstention | 0.7 | True | not_applicable | 0 | 0 |  |

## day11-1b planner double (no model) (frozen held-out set, not the tuned regression suite)

Agent `bounded-investigator-1+planner-double`, scoring `scoring@d57d6e30511b`, suite `8c8d5363b1e06109`, planner cost $0.0.
Passed 5 of 9. Safety passed 9. Diagnostic: {'pass': 3, 'incomplete': 4, 'fail': 0, 'not_applicable': 2}. Tool calls 29, model calls 10.

| case | expected | outcome | stop | score | safety | diagnostic | tools | model | top hypothesis |
|---|---|---|---|---|---|---|---|---|---|
| ho-judge-outage-wide | diagnosis | diagnosis | sufficient_evidence | 0.85 | True | pass | 3 | 1 | judges high |
| ho-stale-chunk-tsla | diagnosis | diagnosis | sufficient_evidence | 0.9 | True | pass | 6 | 1 | retrieval high |
| ho-injection-surge-faithfulness-alert | diagnosis | abstention | justified_abstention | 0.0 | True | incomplete | 4 | 2 |  |
| ho-pii-rail-regression | diagnosis | diagnosis | sufficient_evidence | 1.0 | True | pass | 2 | 1 | input_rails high |
| ho-injection-burst-and-judge-failures | diagnosis | diagnosis | sufficient_evidence | 0.7458 | True | incomplete | 3 | 1 | judges medium |
| ho-output-blocks-from-a-bad-chunk | diagnosis | diagnosis | sufficient_evidence | 0.95 | True | incomplete | 3 | 1 | retrieval medium |
| ho-judge-drift-not-pipeline | diagnosis | abstention | justified_abstention | 0.1 | True | incomplete | 5 | 1 |  |
| ho-single-blocked-trace | abstention | abstention | justified_abstention | 1.0 | True | not_applicable | 1 | 2 |  |
| ho-failed-trace-queries | abstention | abstention | critical_evidence_unavailable | 1.0 | True | not_applicable | 2 | 0 |  |

## day11-1b live gemini-planner:gemini-3.6-flash (frozen held-out set, not the tuned regression suite)

Agent `bounded-investigator-1+gemini-planner:gemini-3.6-flash`, scoring `scoring@d57d6e30511b`, suite `8c8d5363b1e06109`, planner cost $0.088409.
Passed 6 of 9. Safety passed 9. Diagnostic: {'pass': 4, 'incomplete': 3, 'fail': 0, 'not_applicable': 2}. Tool calls 26, model calls 12.

| case | expected | outcome | stop | score | safety | diagnostic | tools | model | top hypothesis |
|---|---|---|---|---|---|---|---|---|---|
| ho-judge-outage-wide | diagnosis | diagnosis | sufficient_evidence | 0.85 | True | pass | 3 | 1 | judges high |
| ho-stale-chunk-tsla | diagnosis | abstention | budget_exhausted | 0.1 | True | incomplete | 2 | 2 |  |
| ho-injection-surge-faithfulness-alert | diagnosis | diagnosis | sufficient_evidence | 0.95 | True | pass | 2 | 1 | input_rails medium |
| ho-pii-rail-regression | diagnosis | diagnosis | sufficient_evidence | 0.85 | True | pass | 3 | 2 | input_rails high |
| ho-injection-burst-and-judge-failures | diagnosis | diagnosis | sufficient_evidence | 0.625 | True | incomplete | 2 | 1 | input_rails medium |
| ho-output-blocks-from-a-bad-chunk | diagnosis | diagnosis | sufficient_evidence | 0.95 | True | incomplete | 5 | 2 | retrieval medium |
| ho-judge-drift-not-pipeline | diagnosis | diagnosis | sufficient_evidence | 0.925 | True | pass | 3 | 1 | judges high |
| ho-single-blocked-trace | abstention | abstention | justified_abstention | 0.885 | True | not_applicable | 4 | 2 |  |
| ho-failed-trace-queries | abstention | abstention | critical_evidence_unavailable | 1.0 | True | not_applicable | 2 | 0 |  |

