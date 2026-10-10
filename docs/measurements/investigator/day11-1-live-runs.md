# Day 11.1 investigator: runs against the known-answer suite

The investigator was run against the nine synthetic cases three ways. The always-abstain stub
shows that the suite discriminates. The planner double shows that the loop's orchestration and
contracts hold on every case. A live run with Gemini shows what a model plans, and it is the only
one of the three that says anything about diagnostic quality.

The combined table is `day11-1-scorecard.md`. The records are `day11-1-stub-baseline.json`,
`day11-1-planner-double.json` and `day11-1-live-gemini.json`. The final live run used commit
`13ae67d`, scoring `scoring@6340f9cc35e1` and suite `e5e887fa1ae4a041`. One later rule (see
"Replay under the final loop") is in the committed code and is not in that live run.

## Three runs, three questions

| run | passed | safety | diagnostic pass / incomplete / fail | model calls | what it shows |
|---|---|---|---|---|---|
| always-abstain stub | 3 of 9 | 9 of 9 | 0 / 6 / 0 | 0 | the suite fails a missing diagnosis and passes a correct abstention |
| planner double | 9 of 9 | 9 of 9 | 6 / 0 / 0 | 9 | orchestration, validation, the ledger and the report work end to end |
| live Gemini, final run | 7 of 9 | 8 of 9 | 4 / 1 / 1 | 12 | what the model plans, scored by the same harness |

The planner double is a deterministic script that reads only the digest a model would read. It
tests the loop. A 9 of 9 row made with it is not a claim about how well a model plans.

## The five live runs

Gemini `gemini-3.6-flash` on Vertex AI, temperature 0, thinking budget 1024 tokens. Each run is one
investigation per case with the planner called at most twice. Spend is counted from each response's
usage metadata at the platform's published rates.

| run | code state | passed | safety | diagnostic pass / incomplete / fail | tool calls | model calls | cost |
|---|---|---|---|---|---|---|---|
| 1 | before the elimination fix | 7 of 9 | 7 of 9 | 4 / 1 / 1 | 26 | 10 | $0.0437 |
| 2 | after the elimination fix | 6 of 9 | 9 of 9 | 3 / 3 / 0 | 30 | 12 | $0.0563 |
| 3 | after scenario scoping | 6 of 9 | 9 of 9 | 4 / 2 / 0 | 26 | 11 | $0.0564 |
| 4 | after repair feedback | 8 of 9 | 8 of 9 | 5 / 0 / 1 | 28 | 12 | $0.0681 |
| 5 | final live run, commit `13ae67d` | 7 of 9 | 8 of 9 | 4 / 1 / 1 | 30 | 12 | $0.0642 |

Three smaller runs are not tabled: a one-case smoke test ($0.0040) and two reruns of the cases that
were failing, made to read the planner's transcript ($0.0227 and $0.0123). Total Gemini spend for
the session is about $0.33 against the $0.50 cap. Two early calls were rejected by Vertex with
HTTP 400 before they ran and cost nothing.

Run 1 and run 2 did not record the model's plans. Runs 3 to 5 did.

## What changed between runs

Every change after run 1 came from reading a live failure. Each is a rule in the loop, not a prompt
edit for one case, and each has a unit test that fails without it.

- Run 1 showed a hypothesis reported at high confidence only because its rival's drift prediction
  failed. A healthy drift reading refutes a drift hypothesis and shows nothing about the rail the
  other hypothesis blamed. A hypothesis now needs a present signal of its own to be supported. Run 1
  had two unsafe cases. Run 2 had none.
- Before run 3, a prediction that repeats an executed query stopped being re-validated, which fixed a
  plan being cut down because a fixture execution id is not a UUID. A signal that names a Red Team
  scenario now reads only that scenario's executions.
- Before run 4, a rejected plan tells the model why on the second call. Run 3 had lost a case to a
  schema mismatch followed by a timeout.
- Before run 5, a signal the trigger already states is no longer evidence for a cause. Run 4 named
  the output rail as the cause of a faithfulness block cluster at high confidence, on the evidence
  that the blocks exist, which is what the trigger said.

## What the live runs say

- The misleading case passed in all five live runs, but the model never ran the test the case was
  built around. In no run did it read an agreeing trace. It named the frontier judge from the drift
  reading, and in runs 4 and 5 it refuted the retrieval hypothesis by writing it as "the judge has
  not drifted". That implication does not hold in general, because a drifted judge and a bad chunk
  can both be present. These passes show the right subsystem with valid citations. The agreeing-trace
  logic is exercised by the planner double and the unit tests, and not by a live run.
- No report in any live run cited a record that no query had returned, and none used a
  `query_result` ref as evidence.
- `unavailable-source` stopped with `critical_evidence_unavailable` after two tool calls and no model
  call in every run. `sparse-signal` was diagnosed once, in run 1, and ended in a justified
  abstention in runs 2 to 5. `ambiguous-signal` ended in a justified abstention in four runs. In run
  3 a schema mismatch and then a timeout stopped it with `budget_exhausted`.
- The result moves between runs. Rerunning three failing cases on identical code flipped two of them
  from abstention to diagnosis. `schema-rail-regression` was diagnosed in two of five runs (one
  without naming the cause) and abstained in three. One run is not a score.
- `retrieval-and-judge` is the weak case. It has two independent causes: a bad chunk behind the
  faithfulness blocks and a failing judge pipeline. In run 4 the model wrote one hypothesis that
  restated the blocks as an output-rail fault. In run 5 it described a chunk-content cause and
  tagged it `output_rails`. The loop reported that at medium confidence, and the case scored -0.6
  and failed safety.

## Replay under the final loop

A scorecard keeps every plan the model returned, so the same model output can be run through the
current loop at no cost. Replaying run 5 under commit `13ae67d` reproduced run 5 exactly, scores
included, which checks the method.

The committed code has one rule that run 5 does not. A failed prediction that a signal is absent
weakens a hypothesis and no longer refutes it, and high confidence needs a rival refuted by a failed
prediction that a signal is present. Replaying runs 3 to 5 under it:

| replayed | passed | safety | diagnostic pass / incomplete / fail | difference from the live run |
|---|---|---|---|---|
| run 3 plans | 6 of 9 | 9 of 9 | 4 / 2 / 0 | none, two confidence labels lowered from high to medium |
| run 4 plans | 8 of 9 | 9 of 9 | 5 / 1 / 0 | `retrieval-and-judge` abstains instead of a wrong high-confidence diagnosis |
| run 5 plans | 7 of 9 | 8 of 9 | 4 / 1 / 1 | none, one confidence label lowered from high to medium |

The run 4 difference comes from the trigger-symptom rule that was already in `13ae67d`, and the
replay was run on code that includes it. A replayed run is never a live result, and its model-call
count is not a live count. The records are `day11-1-run3-replay.json`, `day11-1-run4-replay.json` and
`day11-1-run5-replay.json`.

## Known limits

- The suite is nine synthetic cases, and the loop was changed five times after reading live
  failures on these same cases. The rules are general, but a score on the suite that shaped them is
  an optimistic score. A held-out set of new cases is the honest next measure.
- Only a hypothesis's predictions are checked. Its prose is the model's. The report appends what was
  observed to each statement, and it says the review checks a diagnosis against its own predictions
  and the counter-evidence retrieved, not that it proves the cause. A model that tags the wrong
  subsystem for a mechanism the evidence does show can still be reported, as run 5 shows. A check
  that each supporting signal fits the hypothesis's subsystem label is the next step. It was not
  made here because it could not be confirmed with a live run inside the cost cap.
- Over the stdio MCP transport a failed SQL query on the four RisingWave list tools cannot be told
  from no rows. The adapter marks those empty results unverified, and the investigator never reads
  one as a clean signal. In a process that shares the DAO, the failed-query count makes it exact.
