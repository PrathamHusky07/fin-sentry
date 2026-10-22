import { expect, test } from "@playwright/test";
import {
  DISAGREEMENT_IS_LIVE,
  DISAGREEMENT_TRACE_ID,
  RERUN_TRACE_ID,
} from "./demo-record";

/**
 * The configured demonstration records (lib/demo-record.json) against the real store. The
 * file must never claim more than the store holds: a record marked live has to be found live,
 * a historical one has to be absent, and the re-asked trace has to be a complete answer that
 * is a different trace from the original. Reads the real gateway. Nothing here calls a model.
 */

interface TraceBody {
  found: boolean;
  rag_status?: string;
  query?: string;
  judge_state?: string;
  flash?: { status?: string } | null;
  frontier?: { sampled?: boolean } | null;
}

test("the configured disagreement is exactly as live as the file says", async ({
  request,
}) => {
  const res = await request.get(`/ops/traces/${DISAGREEMENT_TRACE_ID}`);
  const body = (await res.json()) as TraceBody;
  expect(body.found).toBe(DISAGREEMENT_IS_LIVE);
  const list = await request.get("/ops/traces?disagreement=true&limit=20");
  const traces = ((await list.json()) as { traces: { app_trace_id: string }[] })
    .traces;
  if (DISAGREEMENT_IS_LIVE) {
    expect(traces.map((t) => t.app_trace_id)).toContain(DISAGREEMENT_TRACE_ID);
  } else {
    // A historical record means the store holds no disagreement to feature.
    expect(traces).toEqual([]);
  }
});

test("the re-asked Amazon trace is a different, complete answer with no disagreement", async ({
  request,
  page,
}) => {
  expect(RERUN_TRACE_ID).not.toBe(DISAGREEMENT_TRACE_ID);
  const res = await request.get(`/ops/traces/${RERUN_TRACE_ID}`);
  const body = (await res.json()) as TraceBody;
  expect(body.found).toBe(true);
  expect(body.rag_status).toBe("success");
  expect(body.query).toContain("net income attributable to shareholders");
  expect(body.flash?.status).toBe("complete");
  expect(body.frontier?.sampled).toBe(false);

  // The Agent page says so under the expired original and links to it, and claims no
  // disagreement.
  await page.goto("/agent");
  const note = page.locator("[data-rerun='available']");
  await expect(note).toBeVisible();
  await expect(note).toContainText("not the original");
  await expect(note).toContainText("shows no disagreement");
  await expect(
    note.getByRole("link", { name: "Open the new trace" }),
  ).toHaveAttribute("href", `/investigations?trace=${RERUN_TRACE_ID}`);
});
