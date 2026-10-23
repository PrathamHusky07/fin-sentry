/**
 * Mirrors finsentry/events/metrics_snapshot.py field-for-field. Pydantic
 * serializes these models with their exact Python (snake_case) field names
 * -- this type matches the real wire shape, not a transformed one.
 */

interface SectionFreshness {
  window_start?: string | null;
  window_end?: string | null;
  stale: boolean;
}

export interface ThroughputMetrics extends SectionFreshness {
  total_requests: number | null;
  success_count: number | null;
  blocked_count: number | null;
  error_count: number | null;
  avg_latency_ms: number | null;
  p95_latency_ms: number | null;
}

export interface FaithfulnessMetrics extends SectionFreshness {
  verdicts_count: number | null;
  avg_faithfulness: number | null;
  complete_count: number | null;
  skipped_count: number | null;
}

export interface RelevanceMetrics extends SectionFreshness {
  verdicts_count: number | null;
  avg_answer_relevance: number | null;
  avg_context_relevance: number | null;
}

export interface TokenUsageMetrics extends SectionFreshness {
  input_tokens_total: number | null;
  output_tokens_total: number | null;
  thoughts_tokens_total: number | null;
  gemini_calls_total: number | null;
  cost_total_usd: number | null;
}

export interface JudgeCostMetrics extends SectionFreshness {
  cost_total_usd: number | null;
}

export interface FrontierMetrics {
  window_minutes: number;
  verdict_counts: Record<string, number>;
  disagreement_counts: Record<string, number>;
  latest_window_end: string | null;
  stale: boolean;
}

export interface MetricsSnapshot {
  generated_at: string;
  risingwave_connected: boolean;
  throughput: ThroughputMetrics | null;
  faithfulness: FaithfulnessMetrics | null;
  relevance: RelevanceMetrics | null;
  tokens: TokenUsageMetrics | null;
  cost: JudgeCostMetrics | null;
  frontier: FrontierMetrics | null;
}
