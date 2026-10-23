import {
  asObject,
  investigationEvents,
  investigations,
  num,
  numOrNull,
  str,
  strOrNull,
  ArchiveUnavailableError,
  type JsonObject,
} from "@/lib/archive/files";
import { micros, utcZ, utcZOrNull } from "@/lib/archive/time";
import type {
  Detail,
  Leading,
  Listing,
  Status,
  Summary,
  TimelineEntry,
} from "@/lib/incidents";

/**
 * The investigation routes over the archived tables, shaped the way finsentry/investigator/api.py
 * shapes them. A row's state, report and usage are the model's own stored dump and pass through.
 * The summary fields the API derives from them are derived here the same way.
 */

const MAX_PAGE = 50;
const STALE_AFTER_MINUTES = 5;

function objectOrNull(row: JsonObject, key: string): JsonObject | null {
  const v = row[key];
  return v === null || v === undefined ? null : asObject(v);
}

function leading(report: JsonObject | null): Leading | null {
  if (report === null || report["outcome"] !== "diagnosis") return null;
  const ranked = report["ranked_hypotheses"];
  if (!Array.isArray(ranked) || ranked.length === 0) return null;
  const top = ranked
    .map(asObject)
    .reduce((a, b) => (num(b, "rank") < num(a, "rank") ? b : a));
  return {
    hypothesis_id: str(top, "hypothesis_id"),
    subsystem: str(top, "subsystem") as Leading["subsystem"],
    confidence: str(top, "confidence") as Leading["confidence"],
    statement: str(top, "statement"),
  };
}

function summary(
  row: JsonObject,
  queryEvents: number | null,
  nowMs: number,
): Summary {
  const request = asObject(row["request"]);
  const state = objectOrNull(row, "state");
  const report = objectOrNull(row, "report");
  const usage = objectOrNull(row, "usage");
  const model = usage === null ? null : asObject(usage["model"]);
  const status = str(row, "status") as Status;
  const reference = request["reference_id"];
  const description = request["description"];
  const kind = str(request, "kind");
  const window = asObject(request["window"]);
  const hypotheses = state === null ? null : state["hypotheses"];
  const executed = state === null ? null : state["executed_queries"];
  if (
    (hypotheses !== null && !Array.isArray(hypotheses)) ||
    (executed !== null && !Array.isArray(executed))
  ) {
    throw new ArchiveUnavailableError(
      "archive investigation state is malformed",
    );
  }
  const heartbeat = micros(str(row, "heartbeat_at"));
  return {
    investigation_id: str(row, "investigation_id"),
    incident_id: str(row, "incident_id"),
    status,
    outcome: strOrNull(row, "outcome") as Summary["outcome"],
    origin: str(row, "origin") as Summary["origin"],
    planner: str(row, "planner"),
    created_at: utcZ(str(row, "created_at")),
    finished_at: utcZOrNull(strOrNull(row, "finished_at")),
    trigger: {
      kind: kind as Summary["trigger"]["kind"],
      reference_id: typeof reference === "string" ? reference : null,
      description:
        typeof description === "string" && description !== ""
          ? description
          : kind,
    },
    scope: {
      endpoint:
        typeof request["endpoint"] === "string" ? request["endpoint"] : null,
      ticker: typeof request["ticker"] === "string" ? request["ticker"] : null,
      trace_ids: [],
    },
    window: {
      start: utcZ(str(window, "start")),
      end: utcZ(str(window, "end")),
    },
    stopping_reason: strOrNull(
      row,
      "stopping_reason",
    ) as Summary["stopping_reason"],
    leading: leading(report),
    hypotheses: hypotheses === null ? null : hypotheses.length,
    queries: executed === null ? queryEvents : executed.length,
    model_calls: model === null ? null : num(model, "calls"),
    cost_usd: model === null ? null : numOrNull(model, "cost_usd"),
    error: strOrNull(row, "error"),
    stale:
      status === "running" &&
      nowMs - heartbeat / 1000 > STALE_AFTER_MINUTES * 60_000,
  };
}

const newestFirst = (a: JsonObject, b: JsonObject) =>
  micros(str(b, "created_at")) - micros(str(a, "created_at"));

export interface InvestigationFilter {
  limit: number;
  offset: number;
  status: string | null;
}

export async function investigationList(
  f: InvestigationFilter,
): Promise<Listing> {
  if (f.limit < 1 || f.limit > MAX_PAGE) {
    throw new RangeError(`limit must be between 1 and ${MAX_PAGE}`);
  }
  const rows = (await investigations())
    .filter((r) => f.status === null || str(r, "status") === f.status)
    .sort(newestFirst);
  const now = Date.now();
  const page = rows.slice(f.offset, f.offset + f.limit + 1);
  return {
    investigations: page.slice(0, f.limit).map((r) => summary(r, null, now)),
    next_offset: page.length > f.limit ? f.offset + f.limit : null,
  };
}

export async function investigationDetail(id: string): Promise<Detail | null> {
  const [rows, events] = await Promise.all([
    investigations(),
    investigationEvents(),
  ]);
  const row = rows.find((r) => str(r, "investigation_id") === id);
  if (row === undefined) return null;
  const timeline: TimelineEntry[] = events
    .filter((e) => str(e, "investigation_id") === id)
    .sort((a, b) => num(a, "seq") - num(b, "seq"))
    .map((e) => ({
      seq: num(e, "seq"),
      at: utcZ(str(e, "at")),
      elapsed_s: num(e, "elapsed_s"),
      event: asObject(e["payload"]) as unknown as TimelineEntry["event"],
    }));
  const queryEvents = timeline.filter((t) => t.event.kind === "query").length;
  return {
    ...summary(row, queryEvents, Date.now()),
    heartbeat_at: utcZ(str(row, "heartbeat_at")),
    timeline,
    state: objectOrNull(row, "state") as unknown as Detail["state"],
    report: objectOrNull(row, "report") as unknown as Detail["report"],
    usage: objectOrNull(row, "usage") as unknown as Detail["usage"],
  };
}
