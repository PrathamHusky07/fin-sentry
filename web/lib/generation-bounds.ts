/**
 * The limits around the one model call, as set in finsentry/gateway/main.py and
 * finsentry/gateway/circuit_breaker.py. These are code constants, not stored data, so the page
 * that shows them says where each is set. lib/generation-bounds.test.ts reads the Python source
 * and fails if any number here stops matching it.
 */
export const GENERATION_BOUNDS = {
  /** Total wall time for the model call across every retry (`_RAG_BUDGET`). */
  callBudgetSeconds: 20,
  /** The longest one attempt may run (`_ATTEMPT_CAP`). */
  attemptCapSeconds: 15,
  /** The end-to-end limit for the whole request, rails included (`_REQUEST_DEADLINE`). */
  requestDeadlineSeconds: 60,
  /** Failures that open the breaker (`failure_threshold`). */
  breakerFailures: 5,
  /** How long the breaker stays open before one probe is allowed (`recovery_timeout`). */
  breakerOpenSeconds: 30,
} as const;

/** The reasons the output schema rail gives when the model's reply breaks the answer contract
 * (finsentry/rails/output/guardrails_schema.py), in the order the rail checks them. */
export const SCHEMA_RAIL_REASONS = [
  "malformed_json",
  "schema_violation",
  "hallucinated_citation",
  "empty_citations_with_non_low_confidence",
] as const;

export type SchemaRailReason = (typeof SCHEMA_RAIL_REASONS)[number];
