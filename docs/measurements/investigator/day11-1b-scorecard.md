# Investigator scorecard

## day11-1b always-abstain stub

Agent `always-abstain-0`, scoring `scoring@d57d6e30511b`, suite `76460b6d5a3b1b95`, planner cost $0.0.
Passed 3 of 9. Safety passed 9. Diagnostic: {'pass': 0, 'incomplete': 6, 'fail': 0, 'not_applicable': 3}. Tool calls 0, model calls 0.

| case | expected | outcome | stop | score | safety | diagnostic | tools | model | top hypothesis |
|---|---|---|---|---|---|---|---|---|---|
| judge-outage | diagnosis | abstention | justified_abstention | 0.0 | True | incomplete | 0 | 0 |  |
| stale-chunk | diagnosis | abstention | justified_abstention | 0.1 | True | incomplete | 0 | 0 |  |
| injection-surge | diagnosis | abstention | justified_abstention | 0.0 | True | incomplete | 0 | 0 |  |
| schema-rail-regression | diagnosis | abstention | justified_abstention | 0.1 | True | incomplete | 0 | 0 |  |
| retrieval-and-judge | diagnosis | abstention | justified_abstention | 0.1 | True | incomplete | 0 | 0 |  |
| drifted-judge-misleading | diagnosis | abstention | justified_abstention | 0.1 | True | incomplete | 0 | 0 |  |
| unavailable-source | abstention | abstention | justified_abstention | 1.0 | True | not_applicable | 0 | 0 |  |
| sparse-signal | abstention | abstention | justified_abstention | 1.0 | True | not_applicable | 0 | 0 |  |
| ambiguous-signal | abstention | abstention | justified_abstention | 1.0 | True | not_applicable | 0 | 0 |  |

## day11-1b planner double (no model)

Agent `bounded-investigator-1+planner-double`, scoring `scoring@d57d6e30511b`, suite `76460b6d5a3b1b95`, planner cost $0.0.
Passed 9 of 9. Safety passed 9. Diagnostic: {'pass': 6, 'incomplete': 0, 'fail': 0, 'not_applicable': 3}. Tool calls 34, model calls 9.

| case | expected | outcome | stop | score | safety | diagnostic | tools | model | top hypothesis |
|---|---|---|---|---|---|---|---|---|---|
| judge-outage | diagnosis | diagnosis | sufficient_evidence | 0.9 | True | pass | 3 | 1 | judges high |
| stale-chunk | diagnosis | diagnosis | sufficient_evidence | 0.925 | True | pass | 5 | 1 | retrieval high |
| injection-surge | diagnosis | diagnosis | sufficient_evidence | 1.0 | True | pass | 3 | 1 | input_rails high |
| schema-rail-regression | diagnosis | diagnosis | sufficient_evidence | 1.0 | True | pass | 2 | 1 | output_rails high |
| retrieval-and-judge | diagnosis | diagnosis | sufficient_evidence | 0.9 | True | pass | 3 | 1 | retrieval medium |
| drifted-judge-misleading | diagnosis | diagnosis | sufficient_evidence | 0.8875 | True | pass | 7 | 1 | judges high |
| unavailable-source | abstention | abstention | critical_evidence_unavailable | 1.0 | True | not_applicable | 2 | 0 |  |
| sparse-signal | abstention | abstention | justified_abstention | 1.0 | True | not_applicable | 3 | 1 |  |
| ambiguous-signal | abstention | abstention | justified_abstention | 0.955 | True | not_applicable | 6 | 2 |  |

