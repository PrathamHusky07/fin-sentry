import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { RequestFlow } from "@/components/request-flow";
import type { RequestFlow as RequestFlowData } from "@/lib/overview-data";

const FLOW: RequestFlowData = {
  total: 10,
  stoppedAt: { input: 1, retrieval: 0, output: 1 },
  errored: 0,
  delivered: 8,
  deliveredComplete: 7,
  deliveredPartial: 1,
  deliveredUnjudged: 0,
  deliveredJudgeFailed: 0,
};

describe("RequestFlow copy", () => {
  const html = renderToStaticMarkup(
    <RequestFlow flow={FLOW} frontierCount={3} />,
  );

  it("describes the frontier count as selected, not as persisted verdicts", () => {
    expect(html).toContain("3 executions");
    expect(html).toContain("selected for frontier review");
    expect(html).not.toContain("persisted frontier verdict");
  });

  it("does not claim a delivered answer carried citations", () => {
    expect(html).toContain("An answer was returned");
    expect(html).not.toContain("with citations");
  });
});
