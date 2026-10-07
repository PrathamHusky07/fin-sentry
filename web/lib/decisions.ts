/**
 * The engineering decisions shown on the landing page. Each entry is a real
 * choice made in this build, read from the build log and the backend
 * source. The prose names no files: where the code backs a claim, the
 * claim is specific enough to check, and where the build is narrower than
 * the aspiration, the tradeoff says so.
 */
export interface Decision {
  title: string;
  problem: string;
  decision: string;
  tradeoff: string;
  consequence: string;
}

export const DECISIONS: Decision[] = [
  {
    title: "Preserve execution identity",
    problem:
      "A summary can hide the one case that matters. Repeated questions look identical, and a view that groups them loses which run went wrong.",
    decision:
      "Investigations keeps one row per persisted execution, blocks and errors included, and never groups, samples or deduplicates. Summary pages group only exact repeats of a ticker and question, and every group links to its individual runs.",
    tradeoff:
      "More rows to scan. The grouping rule is an exact string match, so a reworded question counts as a different one.",
    consequence:
      "Any number on a summary page can be walked down to the executions behind it.",
  },
  {
    title: "Resolve every trace to its latest verdict",
    problem:
      "A trace with two judge verdicts, from a retry or a re-score, appeared twice in the list and could disagree with its own detail view about which verdict counted.",
    decision:
      "The list and the detail view both pick the newest verdict per trace with the same window rule. A live regression test publishes two verdict events for one trace and asserts a single row.",
    tradeoff:
      "These views show only the newest verdict for a trace, so a re-score replaces the earlier reading on screen.",
    consequence:
      "The list, the filters and the trace detail agree about every execution.",
  },
  {
    title: "Give a failed judge its own state",
    problem:
      "One failed label covered two different facts: a request stopped before there was anything to judge, and a judge that errored on an answer that was delivered fine.",
    decision:
      "Evaluation has five states. The fifth, judge pipeline error, applies only when the request succeeded and the judge scored nothing. It has its own badge and its own filter.",
    tradeoff:
      "No persisted execution has landed in that state yet, so it is exercised by tests and a data check, not by an incident.",
    consequence:
      "Coverage numbers cannot blame an answer for the judge’s outage, or the reverse.",
  },
  {
    title: "Fail safe in diagnostics",
    problem:
      "When the schema rail rejected a reply, the log recorded the first 500 characters of raw model output, and nothing could turn that off.",
    decision:
      "The snippet is logged only when a diagnostic flag is set, and the default configuration leaves it unset. Two tests prove it is absent by default and present only with the flag.",
    tradeoff: "Debugging a malformed reply now takes an explicit opt-in.",
    consequence:
      "Forgetting the flag costs a debugging step, not model output sitting in the logs.",
  },
  {
    title: "Measure the judge, with asymmetric thresholds",
    problem:
      "A judge is a model and can be wrong. Scoring answers says nothing about whether the scorer is reliable, and one cutoff would flap between healthy and drifting.",
    decision:
      "The frontier judge is scored against a labeled financial hallucination benchmark with Cohen’s kappa. Drift begins at 0.43 and recovery requires 0.54, so the state has a gap to cross.",
    tradeoff:
      "One manual reading is on record. The controller that applies the thresholds is built and tested but not yet wired into the gateway, and the flash judge is not calibrated.",
    consequence:
      "The dashboard can say how far the second opinion can be trusted, and when that reading was taken.",
  },
  {
    title:
      "Keep generation local, move the second opinion off the request path",
    problem:
      "Judging inline would put a hosted model’s latency and failures into every answer a user waits for.",
    decision:
      "The model call is bounded: a 20 second budget, a 15 second cap per attempt, and a circuit breaker that opens for 30 seconds after five failures. The gateway then publishes one event and moves on. A flash judge scores every answer, and a deterministic one-in-ten sample gets the frontier review.",
    tradeoff:
      "Delivery is at-most-once, so an event can be lost, and evaluation data is telemetry, not a ledger. The one check left on the path, request-time faithfulness, fails open when Gemini is unavailable.",
    consequence:
      "Answer latency does not depend on the judges, and a judge outage cannot block an answer.",
  },
];
