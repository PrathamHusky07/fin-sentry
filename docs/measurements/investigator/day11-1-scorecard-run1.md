# Investigator scorecard

## day11-1 always-abstain stub

Agent `always-abstain-0`, scoring `scoring@6340f9cc35e1`, suite `e5e887fa1ae4a041`, planner cost $0.0.
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

## day11-1 planner double (no model)

Agent `bounded-investigator-1+planner-double`, scoring `scoring@6340f9cc35e1`, suite `e5e887fa1ae4a041`, planner cost $0.0.
Passed 9 of 9. Safety passed 9. Diagnostic: {'pass': 6, 'incomplete': 0, 'fail': 0, 'not_applicable': 3}. Tool calls 34, model calls 9.

| case | expected | outcome | stop | score | safety | diagnostic | tools | model | top hypothesis |
|---|---|---|---|---|---|---|---|---|---|
| judge-outage | diagnosis | diagnosis | sufficient_evidence | 0.9 | True | pass | 3 | 1 | judges medium |
| stale-chunk | diagnosis | diagnosis | sufficient_evidence | 0.925 | True | pass | 5 | 1 | retrieval high |
| injection-surge | diagnosis | diagnosis | sufficient_evidence | 1.0 | True | pass | 3 | 1 | input_rails high |
| schema-rail-regression | diagnosis | diagnosis | sufficient_evidence | 1.0 | True | pass | 2 | 1 | output_rails high |
| retrieval-and-judge | diagnosis | diagnosis | sufficient_evidence | 0.9 | True | pass | 3 | 1 | retrieval high |
| drifted-judge-misleading | diagnosis | diagnosis | sufficient_evidence | 0.8875 | True | pass | 7 | 1 | judges high |
| unavailable-source | abstention | abstention | critical_evidence_unavailable | 1.0 | True | not_applicable | 2 | 0 |  |
| sparse-signal | abstention | abstention | justified_abstention | 1.0 | True | not_applicable | 3 | 1 |  |
| ambiguous-signal | abstention | abstention | justified_abstention | 0.955 | True | not_applicable | 6 | 2 |  |

## day11-1 live gemini-planner:gemini-3.6-flash

Agent `bounded-investigator-1+gemini-planner:gemini-3.6-flash`, scoring `scoring@6340f9cc35e1`, suite `e5e887fa1ae4a041`, planner cost $0.043673.
Passed 7 of 9. Safety passed 7. Diagnostic: {'pass': 4, 'incomplete': 1, 'fail': 1, 'not_applicable': 3}. Tool calls 26, model calls 10.

| case | expected | outcome | stop | score | safety | diagnostic | tools | model | top hypothesis |
|---|---|---|---|---|---|---|---|---|---|
| judge-outage | diagnosis | diagnosis | sufficient_evidence | 0.95 | True | pass | 2 | 1 | judges high |
| stale-chunk | diagnosis | diagnosis | sufficient_evidence | 0.825 | True | pass | 4 | 1 | retrieval high |
| injection-surge | diagnosis | diagnosis | sufficient_evidence | 0.95 | True | pass | 2 | 1 | input_rails high |
| schema-rail-regression | diagnosis | diagnosis | sufficient_evidence | 0.835 | True | incomplete | 4 | 2 | output_rails high |
| retrieval-and-judge | diagnosis | diagnosis | sufficient_evidence | -0.25 | False | fail | 2 | 1 | output_rails low |
| drifted-judge-misleading | diagnosis | diagnosis | sufficient_evidence | 0.85 | True | pass | 4 | 1 | judges high |
| unavailable-source | abstention | abstention | critical_evidence_unavailable | 1.0 | True | not_applicable | 2 | 0 |  |
| sparse-signal | abstention | diagnosis | sufficient_evidence | -1.0 | False | not_applicable | 2 | 1 | output_rails high |
| ambiguous-signal | abstention | abstention | justified_abstention | 0.885 | True | not_applicable | 4 | 2 |  |

