import { describe, expect, it } from "vitest";
import { consequences } from "@/components/red-team-execute";
import type { ScenarioView } from "@/lib/red-team";

const s = (id: string, executor: string): ScenarioView =>
  ({ id, executor }) as ScenarioView;

describe("what a run will do, read from the registry", () => {
  it("names the scenarios that send a real gateway request and counts the direct ones", () => {
    expect(
      consequences([
        s("DI-001", "gateway_route"),
        s("PII-001", "input_rails"),
        s("MS-001", "gateway_route"),
        s("OUT-001", "output_rails"),
      ]),
    ).toEqual({
      total: 4,
      gatewayIds: ["DI-001", "MS-001"],
      directCount: 2,
    });
  });

  it("says nothing about the gateway for a run that sends none", () => {
    expect(consequences([s("OUT-001", "output_rails")]).gatewayIds).toEqual([]);
  });
});
