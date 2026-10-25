import { describe, expect, it, vi } from "vitest";
import { ArchiveUnavailableError, parseJsonl } from "@/lib/archive/files";
import {
  investigationDetail,
  investigationList,
} from "@/lib/archive/investigations";
import { serveArchive } from "@/lib/archive/serve";

// Expected ids, counts and costs come from a separate read of docs/demo-archive/postgres.

const LIVE = "a771a7e4-3354-4c10-8bb2-d506f1f713e7";
const DIAGNOSIS = "43751b14-b080-4f5b-8391-33b914f12f22";
const INTERRUPTED = "90e8aa78-73c1-4a02-8b03-16cbae8f7b08";
const FAILED = "0b3a187f-36c7-4bb8-b230-6e62bad9be54";

describe("investigationList", () => {
  it("lists the seven archived sessions, newest first", async () => {
    const list = await investigationList({
      limit: 20,
      offset: 0,
      status: null,
    });
    expect(list.investigations.map((i) => i.investigation_id)).toEqual([
      LIVE,
      INTERRUPTED,
      FAILED,
      "0141f52e-3acb-4dd9-af23-f69829c2ea1f",
      "b8641a99-90da-41ed-a5a5-f79ec3b5e4de",
      "83de48d7-b3bc-4d1e-b1d3-ea1f5226d12d",
      DIAGNOSIS,
    ]);
    expect(list.next_offset).toBeNull();
  });

  it("derives the summary fields from the stored state, report and usage", async () => {
    const { investigations } = await investigationList({
      limit: 20,
      offset: 0,
      status: null,
    });
    const live = investigations.find((i) => i.investigation_id === LIVE);
    expect(live).toMatchObject({
      origin: "live",
      status: "completed",
      outcome: "abstention",
      hypotheses: 2,
      queries: 3,
      model_calls: 2,
      cost_usd: 0.008509,
      leading: null,
      created_at: "2026-10-20T22:12:10.102798Z",
      stale: false,
    });
    const diagnosis = investigations.find(
      (i) => i.investigation_id === DIAGNOSIS,
    );
    expect(diagnosis?.outcome).toBe("diagnosis");
    expect(diagnosis?.leading?.hypothesis_id).toBe("h2");
    expect(diagnosis?.leading?.statement).toContain(
      "The frontier judge has drifted",
    );
    expect(diagnosis).toMatchObject({
      hypotheses: 2,
      queries: 7,
      origin: "fixture",
    });
  });

  it("says unknown, not zero, for a session that stored no final state", async () => {
    const { investigations } = await investigationList({
      limit: 20,
      offset: 0,
      status: null,
    });
    const interrupted = investigations.find(
      (i) => i.investigation_id === INTERRUPTED,
    );
    expect(interrupted).toMatchObject({
      status: "interrupted",
      outcome: null,
      hypotheses: null,
      queries: null,
      model_calls: null,
      cost_usd: null,
    });
    expect(interrupted?.error).toContain("stopped before it finished");
  });

  it("filters on status and pages with a next offset", async () => {
    const failed = await investigationList({
      limit: 20,
      offset: 0,
      status: "failed",
    });
    expect(failed.investigations.map((i) => i.investigation_id)).toEqual([
      FAILED,
    ]);
    const page = await investigationList({ limit: 3, offset: 0, status: null });
    expect(page.investigations).toHaveLength(3);
    expect(page.next_offset).toBe(3);
    const tail = await investigationList({ limit: 3, offset: 6, status: null });
    expect(tail.investigations.map((i) => i.investigation_id)).toEqual([
      DIAGNOSIS,
    ]);
    expect(tail.next_offset).toBeNull();
  });
});

describe("investigationDetail", () => {
  it("returns the timeline in sequence with the stored report", async () => {
    const d = await investigationDetail(DIAGNOSIS);
    expect(d?.timeline).toHaveLength(10);
    expect(d?.timeline.map((t) => t.seq)).toEqual(
      [...d!.timeline.map((t) => t.seq)].sort((a, b) => a - b),
    );
    expect(d?.timeline[0].event.kind).toBe("query");
    expect(d?.report?.outcome).toBe("diagnosis");
    expect(d?.report?.ranked_hypotheses.length).toBeGreaterThan(0);
    expect(d?.state?.executed_queries).toHaveLength(7);
    expect(d?.usage?.model.planner).toBeTypeOf("string");
  });

  it("counts the query events for a session whose state was never stored", async () => {
    const d = await investigationDetail(INTERRUPTED);
    expect(d?.state).toBeNull();
    expect(d?.report).toBeNull();
    expect(d?.timeline).toHaveLength(1);
    expect(d?.queries).toBe(
      d?.timeline.filter((t) => t.event.kind === "query").length,
    );
  });

  it("is null for an id that is not in the archive", async () => {
    expect(
      await investigationDetail("00000000-0000-0000-0000-000000000000"),
    ).toBeNull();
  });
});

describe("serveArchive", () => {
  it("answers a stored session over the gateway path with the same shape", async () => {
    const res = await serveArchive(`/ops/investigations/${LIVE}`);
    expect(res.status).toBe(200);
    const body = (await res.json()) as {
      investigation_id: string;
      heartbeat_at: string;
    };
    expect(body.investigation_id).toBe(LIVE);
    expect(body.heartbeat_at).toMatch(/Z$/);
  });

  it("answers 404 for a missing record and for a route with no archived source", async () => {
    expect((await serveArchive("/ops/investigations/nope")).status).toBe(404);
    expect((await serveArchive("/ops/redteam/runs/nope")).status).toBe(404);
    // The throughput history has no archived source, unlike the gateway probe.
    const history = await serveArchive("/ops/metrics/throughput/history");
    expect(history.status).toBe(404);
    expect(await history.json()).toEqual({
      error: "this route has no archived record",
    });
    expect((await serveArchive("/v1/rag/query")).status).toBe(404);
  });

  it("answers 422 for a parameter it cannot read", async () => {
    expect((await serveArchive("/ops/traces?limit=abc")).status).toBe(422);
    expect((await serveArchive("/ops/traces?limit=0")).status).toBe(422);
    expect(
      (await serveArchive("/ops/traces?judge_state=invented")).status,
    ).toBe(422);
    expect((await serveArchive("/ops/traces?disagreement=maybe")).status).toBe(
      422,
    );
  });

  it("never enables a run", async () => {
    const res = await serveArchive("/ops/redteam/run-gate");
    expect(await res.json()).toEqual({ runs_enabled: false });
  });

  it("serves the trace list, one trace and the calibration reading", async () => {
    const list = (await (await serveArchive("/ops/traces?limit=2")).json()) as {
      traces: { app_trace_id: string }[];
    };
    expect(list.traces[0].app_trace_id).toBe(
      "b357b1c2-804d-43ef-8b1d-7f1eb5f01287",
    );
    const one = (await (
      await serveArchive("/ops/traces/54cd64af-d7da-4b9e-8ffa-e46da1e27d6b")
    ).json()) as {
      found: boolean;
    };
    expect(one.found).toBe(true);
    const cal = (await (
      await serveArchive("/ops/calibration/health")
    ).json()) as { state: string };
    expect(cal.state).toBe("degraded");
  });
});

describe("a malformed archive", () => {
  it("fails closed with a typed error instead of skipping a line", () => {
    expect(() => parseJsonl('{"a": 1}\n{not json}\n')).toThrow(
      ArchiveUnavailableError,
    );
  });

  it("answers 503 when a file cannot be read", async () => {
    vi.resetModules();
    vi.doMock("node:fs/promises", () => ({
      readFile: () => Promise.reject(new Error("ENOENT")),
    }));
    const { serveArchive: fresh } = await import("@/lib/archive/serve");
    const res = await fresh("/ops/investigations?limit=5");
    expect(res.status).toBe(503);
    expect(await res.json()).toEqual({
      error: "the archived record could not be read",
    });
    vi.doUnmock("node:fs/promises");
  });
});
