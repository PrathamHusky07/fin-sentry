import {
  ArchiveUnavailableError,
  asObject,
  frontierVerdicts,
  judgeVerdicts,
  numOrNull,
  ragResponses,
  str,
  strOrNull,
  type JsonObject,
} from "@/lib/archive/files";
import { micros, utcZ, utcZOrNull } from "@/lib/archive/time";
import type {
  FlashJudgeView,
  FrontierSectionView,
  JudgeState,
  TraceDetailResponse,
  TraceListItem,
  TraceListResponse,
} from "@/lib/trace-api";

/**
 * The trace routes over the three archived stream files. This re-states, in one place, the
 * queries finsentry/dashboard/app.py runs over the RisingWave sources: the same joins, the same
 * latest-row rules and the same judge-state and disagreement rules. The sources are the raw topic
 * records, so there is nothing else to read.
 */

const MAX_LIMIT = 500;
const REAL_FRONTIER_JUDGE_ID = "gemini-rubric";
const DISAGREEMENT_SCORE_DELTA = 0.5;
/** The dashboard leaves the pytest regression probes out of the trace list. Same narrow rule. */
const TEST_TRAFFIC_QUERY_PREFIX = "duplicate-verdict regression probe ";
const TRACE_ID_LENGTH = 36;

export const JUDGE_STATES: readonly JudgeState[] = [
  "evaluated",
  "partially_evaluated",
  "blocked_before_evaluation",
  "judge_failed",
  "never_evaluated",
];

interface RagEvent {
  traceId: string;
  offset: number;
  at: number;
  raw: JsonObject;
}

interface Verdict {
  offset: number;
  at: number;
  raw: JsonObject;
}

interface TraceIndex {
  /** Every archived request, newest first. */
  requests: RagEvent[];
  byTrace: Map<string, RagEvent>;
  judgeByTrace: Map<string, Verdict>;
  frontierByTrace: Map<string, Verdict>;
  /** Every trace with at least one frontier row. */
  frontierSampled: Set<string>;
  /** Traces where the flash score and the real frontier score are far apart. */
  disagreementIds: Set<string>;
}

function newest(items: Verdict[]): Verdict | undefined {
  return items.reduce<Verdict | undefined>(
    (best, v) =>
      best === undefined ||
      v.at > best.at ||
      (v.at === best.at && v.offset > best.offset)
        ? v
        : best,
    undefined,
  );
}

/** Mirrors _real_frontier_evidence: the one gemini-rubric entry that carries evidence. */
function realFrontierEntry(raw: JsonObject): JsonObject | null {
  const results = raw["per_judge_results"];
  if (!Array.isArray(results)) return null;
  for (const entry of results) {
    const e = asObject(entry);
    if (e["judge_id"] === REAL_FRONTIER_JUDGE_ID && e["evidence"] != null) {
      return e;
    }
  }
  return null;
}

let indexPromise: Promise<TraceIndex> | undefined;

async function buildIndex(): Promise<TraceIndex> {
  const [rag, judge, frontier] = await Promise.all([
    ragResponses(),
    judgeVerdicts(),
    frontierVerdicts(),
  ]);

  const requests: RagEvent[] = rag.map((r) => ({
    traceId: str(r.value, "app_trace_id"),
    offset: r.offset,
    at: micros(str(r.value, "timestamp_utc")),
    raw: r.value,
  }));
  requests.sort((a, b) => b.at - a.at || b.offset - a.offset);

  // A trace can have more than one request row. The list shows each, the detail shows the newest.
  const byTrace = new Map<string, RagEvent>();
  for (const r of requests)
    if (!byTrace.has(r.traceId)) byTrace.set(r.traceId, r);

  const judgesByTrace = new Map<string, Verdict[]>();
  for (const j of judge) {
    const id = str(j.value, "app_trace_id");
    const list = judgesByTrace.get(id) ?? [];
    list.push({
      offset: j.offset,
      at: micros(str(j.value, "timestamp_utc")),
      raw: j.value,
    });
    judgesByTrace.set(id, list);
  }
  const judgeByTrace = new Map<string, Verdict>();
  for (const [id, list] of judgesByTrace) {
    const v = newest(list);
    if (v) judgeByTrace.set(id, v);
  }

  const frontiersByTrace = new Map<string, Verdict[]>();
  for (const f of frontier) {
    const id = str(f.value, "app_trace_id");
    const list = frontiersByTrace.get(id) ?? [];
    list.push({
      offset: f.offset,
      at: micros(str(f.value, "evaluation_ts")),
      raw: f.value,
    });
    frontiersByTrace.set(id, list);
  }
  const frontierByTrace = new Map<string, Verdict>();
  for (const [id, list] of frontiersByTrace) {
    const v = newest(list);
    if (v) frontierByTrace.set(id, v);
  }

  // Mirrors _fetch_disagreement_trace_ids: a request, its newest flash verdict (faithfulness
  // complete) and its newest frontier row, where the real frontier score and the flash score are
  // at least 0.5 apart.
  const disagreementIds = new Set<string>();
  for (const id of byTrace.keys()) {
    const j = judgeByTrace.get(id);
    const f = frontierByTrace.get(id);
    if (!j || !f || j.raw["faithfulness_status"] !== "complete") continue;
    const real = realFrontierEntry(f.raw);
    if (real === null) continue;
    const frontierScore = numOrNull(real, "faithfulness_score");
    const flashScore = numOrNull(j.raw, "faithfulness_score");
    if (frontierScore === null || flashScore === null) continue;
    if (Math.abs(flashScore - frontierScore) >= DISAGREEMENT_SCORE_DELTA) {
      disagreementIds.add(id);
    }
  }

  return {
    requests,
    byTrace,
    judgeByTrace,
    frontierByTrace,
    frontierSampled: new Set(frontiersByTrace.keys()),
    disagreementIds,
  };
}

function index(): Promise<TraceIndex> {
  indexPromise ??= buildIndex().catch((error: unknown) => {
    indexPromise = undefined;
    throw error;
  });
  return indexPromise;
}

/** Mirrors _classify_judge_state. The delivery status decides first. */
function classify(judgeStatus: string | null, ragStatus: string): JudgeState {
  if (ragStatus !== "success") return "blocked_before_evaluation";
  if (judgeStatus === "complete") return "evaluated";
  if (judgeStatus === "partial") return "partially_evaluated";
  if (judgeStatus === null) return "never_evaluated";
  return "judge_failed";
}

/** SQL LIKE with % and _ wildcards, case-insensitive, matched anywhere in the text. */
function likeMatcher(pattern: string): RegExp {
  let source = "";
  for (let i = 0; i < pattern.length; i += 1) {
    const ch = pattern[i];
    if (ch === "\\" && i + 1 < pattern.length) {
      i += 1;
      source += pattern[i].replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    } else if (ch === "%") source += "[\\s\\S]*";
    else if (ch === "_") source += "[\\s\\S]";
    else source += ch.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  }
  return new RegExp(`^${source}$`, "i");
}

export interface TraceListParams {
  limit: number;
  offset: number;
  ticker: string | null;
  status: string | null;
  q: string | null;
  judgeState: JudgeState | null;
  frontierSampled: boolean | null;
  disagreement: boolean | null;
}

export async function traceList(
  p: TraceListParams,
): Promise<TraceListResponse> {
  if (p.limit < 1 || p.limit > MAX_LIMIT) {
    throw new RangeError(`limit must be between 1 and ${MAX_LIMIT}`);
  }
  const ix = await index();
  const like = p.q === null ? null : likeMatcher(`%${p.q}%`);

  const items: TraceListItem[] = [];
  for (const r of ix.requests) {
    const query = str(r.raw, "query");
    // The UI list leaves the pytest regression probes out. A probe still opens by its id.
    if (
      query.startsWith(TEST_TRAFFIC_QUERY_PREFIX) &&
      query.length === TEST_TRAFFIC_QUERY_PREFIX.length + TRACE_ID_LENGTH
    ) {
      continue;
    }
    const ragStatus = str(r.raw, "status");
    const ticker = strOrNull(r.raw, "ticker");
    if (p.ticker !== null && ticker !== p.ticker) continue;
    if (p.status !== null && ragStatus !== p.status) continue;
    if (like !== null && !like.test(query) && !like.test(r.traceId)) continue;
    const judge = ix.judgeByTrace.get(r.traceId);
    const state = classify(judge ? str(judge.raw, "status") : null, ragStatus);
    if (p.judgeState !== null && state !== p.judgeState) continue;
    const sampled = ix.frontierSampled.has(r.traceId);
    if (p.frontierSampled !== null && sampled !== p.frontierSampled) continue;
    if (
      p.disagreement !== null &&
      ix.disagreementIds.has(r.traceId) !== p.disagreement
    ) {
      continue;
    }
    items.push({
      app_trace_id: r.traceId,
      timestamp_utc: utcZ(str(r.raw, "timestamp_utc")),
      endpoint: str(r.raw, "endpoint"),
      ticker,
      query,
      rag_status: ragStatus,
      block_reason: strOrNull(r.raw, "block_reason"),
      judge_state: state,
      frontier_sampled: sampled,
    });
  }

  const page = items.slice(p.offset, p.offset + p.limit);
  return {
    traces: page,
    next_offset: page.length === p.limit ? p.offset + p.limit : null,
    // No RisingWave behind this response. The pages do not read the flag.
    risingwave_connected: false,
  };
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((v) => {
    if (typeof v !== "string") {
      throw new ArchiveUnavailableError("archive list holds a non-string");
    }
    return v;
  });
}

function citationList(value: unknown): Record<string, string>[] {
  if (!Array.isArray(value)) return [];
  return value.map((c) => {
    const o = asObject(c);
    const out: Record<string, string> = {};
    for (const [k, v] of Object.entries(o)) {
      if (typeof v !== "string") {
        throw new ArchiveUnavailableError(
          "archive citation holds a non-string",
        );
      }
      out[k] = v;
    }
    return out;
  });
}

function frontierSection(raw: JsonObject | undefined): FrontierSectionView {
  if (raw === undefined) {
    return {
      sampled: false,
      evidence: null,
      note: "frontier not sampled for this trace",
    };
  }
  const real = realFrontierEntry(raw);
  if (real === null) {
    return {
      sampled: true,
      evidence: null,
      note: "frontier evaluated with no real judge recorded",
    };
  }
  const evidence = asObject(real["evidence"]);
  return {
    sampled: true,
    evidence: {
      judge_id: REAL_FRONTIER_JUDGE_ID,
      faithfulness_score: numOrNull(real, "faithfulness_score"),
      rubric_reasoning: strOrNull(evidence, "rubric_reasoning"),
      cited_chunks_supporting: stringList(evidence["cited_chunks_supporting"]),
      cited_chunks_contradicting: stringList(
        evidence["cited_chunks_contradicting"],
      ),
      verdict: str(raw, "verdict"),
      evaluation_ts: utcZ(str(raw, "evaluation_ts")),
    },
    note: "real gemini-rubric evidence for this trace",
  };
}

export async function traceDetail(
  traceId: string,
): Promise<TraceDetailResponse> {
  const ix = await index();
  const r = ix.byTrace.get(traceId);
  if (r === undefined) {
    return {
      app_trace_id: traceId,
      found: false,
      rag_status: null,
      endpoint: null,
      ticker: null,
      query: null,
      answer: null,
      confidence: null,
      model_used: null,
      citations: [],
      retrieved_chunk_ids: [],
      block_reason: null,
      block_rail: null,
      error_kind: null,
      error_detail: null,
      timestamp_utc: null,
      judge_state: "never_evaluated",
      flash: null,
      frontier: frontierSection(undefined),
      risingwave_connected: false,
      note: "no matching rag_events row",
    };
  }

  const judge = ix.judgeByTrace.get(traceId);
  const flash: FlashJudgeView | null = judge
    ? {
        status: str(judge.raw, "status"),
        timestamp_utc: utcZOrNull(strOrNull(judge.raw, "timestamp_utc")),
        faithfulness_score: numOrNull(judge.raw, "faithfulness_score"),
        faithfulness_status: strOrNull(judge.raw, "faithfulness_status"),
        answer_relevance_score: numOrNull(judge.raw, "answer_relevance_score"),
        answer_relevance_status: strOrNull(
          judge.raw,
          "answer_relevance_status",
        ),
        context_relevance_score: numOrNull(
          judge.raw,
          "context_relevance_score",
        ),
        context_relevance_status: strOrNull(
          judge.raw,
          "context_relevance_status",
        ),
      }
    : null;

  const ragStatus = str(r.raw, "status");
  return {
    app_trace_id: traceId,
    found: true,
    rag_status: ragStatus,
    endpoint: str(r.raw, "endpoint"),
    ticker: strOrNull(r.raw, "ticker"),
    query: str(r.raw, "query"),
    answer: strOrNull(r.raw, "answer"),
    confidence: strOrNull(r.raw, "confidence"),
    model_used: strOrNull(r.raw, "model_used"),
    citations: citationList(r.raw["citations"]),
    retrieved_chunk_ids: stringList(r.raw["retrieved_chunk_ids"]),
    block_reason: strOrNull(r.raw, "block_reason"),
    block_rail: strOrNull(r.raw, "block_rail"),
    error_kind: strOrNull(r.raw, "error_kind"),
    error_detail: strOrNull(r.raw, "error_detail"),
    timestamp_utc: utcZ(str(r.raw, "timestamp_utc")),
    judge_state: classify(judge ? str(judge.raw, "status") : null, ragStatus),
    flash,
    frontier: frontierSection(ix.frontierByTrace.get(traceId)?.raw),
    risingwave_connected: false,
    note: "persisted trace snapshot",
  };
}
