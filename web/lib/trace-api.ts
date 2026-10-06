/**
 * Mirrors finsentry/events/trace_api.py field-for-field. Pydantic serializes
 * these models with their exact Python (snake_case) field names -- this
 * type matches the real wire shape, not a transformed one.
 */

export type JudgeState =
  | "evaluated"
  | "partially_evaluated"
  | "blocked_before_evaluation"
  | "judge_failed"
  | "never_evaluated";

export interface TraceListItem {
  app_trace_id: string;
  timestamp_utc: string;
  endpoint: string;
  ticker: string | null;
  query: string;
  rag_status: string;
  block_reason: string | null;
  judge_state: JudgeState;
  frontier_sampled: boolean;
}

export interface TraceListResponse {
  traces: TraceListItem[];
  next_offset: number | null;
  risingwave_connected: boolean;
}

export interface FlashJudgeView {
  status: string;
  timestamp_utc: string | null;
  faithfulness_score: number | null;
  faithfulness_status: string | null;
  answer_relevance_score: number | null;
  answer_relevance_status: string | null;
  context_relevance_score: number | null;
  context_relevance_status: string | null;
}

export interface FrontierEvidenceView {
  judge_id: "gemini-rubric";
  faithfulness_score: number | null;
  rubric_reasoning: string | null;
  cited_chunks_supporting: string[];
  cited_chunks_contradicting: string[];
  verdict: string;
  evaluation_ts: string;
}

export interface FrontierSectionView {
  sampled: boolean;
  evidence: FrontierEvidenceView | null;
  note: string;
}

export interface TraceDetailResponse {
  app_trace_id: string;
  found: boolean;
  rag_status: string | null;
  endpoint: string | null;
  ticker: string | null;
  query: string | null;
  answer: string | null;
  confidence: string | null;
  model_used: string | null;
  citations: Record<string, string>[];
  retrieved_chunk_ids: string[];
  block_reason: string | null;
  block_rail: string | null;
  error_kind: string | null;
  error_detail: string | null;
  timestamp_utc: string | null;
  judge_state: JudgeState;
  flash: FlashJudgeView | null;
  frontier: FrontierSectionView;
  risingwave_connected: boolean;
  note: string;
}

export type CalibrationPosition =
  | "at_or_above_recovery"
  | "between_thresholds"
  | "at_or_below_entry"
  | "insufficient_data";

export interface CalibrationHealthResponse {
  judge_id: string;
  kappa: number | null;
  state: string | null;
  window_n: number | null;
  min_n: number;
  healthy_baseline_kappa: number;
  drift_entry_threshold: number;
  recovery_threshold: number;
  position: CalibrationPosition;
  state_as_of: string | null;
  note: string;
}
