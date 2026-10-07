import type { JudgeState } from "@/lib/trace-api";

/**
 * Human-readable labels for the machine codes the gateway persists. User-
 * facing surfaces show these; the raw codes stay available in the trace
 * detail’s technical record. Every code below was read from the gateway
 * source (finsentry/gateway/main.py, finsentry/rails/output/*), not guessed.
 */

/** Pipeline stage a block belongs to, derived from block_reason. */
export type BlockStage = "input" | "retrieval" | "output";

const BLOCK_REASON_LABEL: Record<string, string> = {
  no_trustworthy_sources: "No trustworthy sources",
  malformed_json: "Malformed JSON",
  schema_violation: "Schema violation",
  hallucinated_citation: "Hallucinated citation",
  empty_citations_with_non_low_confidence: "Missing citations",
  regulated_phrase: "Regulated phrase",
  low_faithfulness: "Low faithfulness",
};

const BLOCK_REASON_MEANING: Record<string, string> = {
  input_rail_blocked:
    "An input rail stopped the request before retrieval. The rail name says which check fired.",
  no_trustworthy_sources:
    "Every retrieved chunk failed the source-trust, injection or PII checks, so there was nothing safe to answer from.",
  malformed_json:
    "The model’s reply could not be parsed as JSON, so the output schema rail rejected it.",
  schema_violation:
    "The reply was valid JSON but not the expected answer, citations and confidence shape.",
  hallucinated_citation:
    "The reply cited a chunk that was not in the retrieved context.",
  empty_citations_with_non_low_confidence:
    "The reply claimed confidence without citing any retrieved chunk.",
  regulated_phrase:
    "The reply contained a phrase the regulated-language rail rejects.",
  low_faithfulness:
    "The request-time faithfulness check scored the answer below its 0.7 threshold.",
};

// block_rail is the finer-grained field for input blocks: the NeMo Colang
// flow name. "check prompt injection" is confirmed in persisted data;
// "check hazard taxonomy" is confirmed on a real false-positive trace.
const INPUT_RAIL_LABEL: Record<string, string> = {
  "check prompt injection": "Prompt injection",
  "check hazard taxonomy": "Hazard taxonomy",
};

export function blockStage(reason: string): BlockStage {
  if (reason === "input_rail_blocked") return "input";
  if (reason === "no_trustworthy_sources") return "retrieval";
  return "output";
}

export const BLOCK_STAGE_LABEL: Record<BlockStage, string> = {
  input: "Input rails",
  retrieval: "Retrieval rail",
  output: "Output rails",
};

/** "Malformed JSON", "Prompt injection", ... Never the raw snake_case. When
 * the persisted block_rail is known it refines input blocks. */
export function blockReasonLabel(
  reason: string,
  blockRail?: string | null,
): string {
  if (reason === "input_rail_blocked") {
    return (blockRail && INPUT_RAIL_LABEL[blockRail]) || "Input rail";
  }
  return BLOCK_REASON_LABEL[reason] ?? humanize(reason);
}

export function blockReasonMeaning(reason: string): string | null {
  return BLOCK_REASON_MEANING[reason] ?? null;
}

const ERROR_KIND_LABEL: Record<string, string> = {
  downstream_unavailable: "Downstream unavailable",
  downstream_rate_limit: "Downstream rate limited",
  downstream_error: "Downstream error",
  input_rail_service_unavailable: "Input rail service unavailable",
  vector_search_failed: "Vector search failed",
};

export function errorKindLabel(kind: string): string {
  return ERROR_KIND_LABEL[kind] ?? humanize(kind);
}

/** The one-line outcome shown in tables and timelines: "Delivered",
 * "Blocked · Malformed JSON", "Error". */
export function outcomeLabel(
  ragStatus: string,
  blockReason: string | null,
  blockRail?: string | null,
  errorKind?: string | null,
): string {
  if (ragStatus === "success") return "Delivered";
  if (ragStatus === "blocked") {
    return blockReason
      ? `Blocked · ${blockReasonLabel(blockReason, blockRail)}`
      : "Blocked";
  }
  if (ragStatus === "error") {
    return errorKind ? `Error · ${errorKindLabel(errorKind)}` : "Error";
  }
  return humanize(ragStatus);
}

export type OutcomeTone = "positive" | "warning" | "failure" | "neutral";

export function outcomeTone(ragStatus: string): OutcomeTone {
  if (ragStatus === "success") return "positive";
  if (ragStatus === "blocked") return "warning";
  if (ragStatus === "error") return "failure";
  return "neutral";
}

/** What each judge state means, in one sentence. Shared by Overview’s
 * coverage explanation and the Investigations filter help. */
export const JUDGE_STATE_MEANING: Record<JudgeState, string> = {
  evaluated:
    "The flash judge scored all three metrics: faithfulness, answer relevance and context relevance.",
  partially_evaluated:
    "The flash judge scored one or two of the three metrics. The others were skipped, for example after a timeout.",
  blocked_before_evaluation:
    "A rail or a downstream failure stopped the request, so there was no answer to judge.",
  never_evaluated:
    "The request succeeded but no flash verdict has been persisted for it.",
  judge_failed:
    "The request succeeded but the judge pipeline scored none of the three metrics.",
};

function humanize(code: string): string {
  const spaced = code.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}
