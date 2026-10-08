import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { StageCards } from "@/components/stage-cards";
import { REQUEST_PATH, stageAnchor } from "@/lib/architecture-data";
import { LAYERS } from "@/lib/architecture-layers";

function hrefOf(markup: string, title: string): string {
  const card = new RegExp(
    `<a [^>]*href="([^"]+)"[^>]*>(?:(?!</a>).)*?<h3[^>]*>${title}</h3>`,
    "s",
  );
  const match = card.exec(markup);
  if (!match) throw new Error(`no card for ${title}`);
  return match[1];
}

describe("stage card destinations", () => {
  const markup = renderToStaticMarkup(<StageCards />);
  const titles = ["Guard", "Retrieve", "Generate", "Judge", "Investigate"];

  it("sends Guard, Retrieve and Generate to three different product surfaces", () => {
    expect(hrefOf(markup, "Guard")).toBe("/overview#flow-heading");
    expect(hrefOf(markup, "Retrieve")).toBe(
      "/investigations?trace=96bca4b5-f707-4a93-b421-2674032849b5",
    );
    expect(hrefOf(markup, "Generate")).toBe("/operations");
  });

  it("keeps Judge and Investigate on their own targets", () => {
    expect(hrefOf(markup, "Judge")).toBe("/architecture#evaluation-plane");
    expect(hrefOf(markup, "Investigate")).toBe("/investigations");
  });

  it("never gives two cards the same destination", () => {
    const hrefs = titles.map((t) => hrefOf(markup, t));
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });
});

describe("request path anchors", () => {
  const steps = LAYERS.find((l) => l.id === "request-path")!.outline.flatMap(
    (lane) => lane.steps,
  );

  it("gives every outline step the outline id of its pipeline stage, in order", () => {
    expect(steps.map((s) => s.anchor)).toEqual(
      REQUEST_PATH.map((id) => stageAnchor(id, "outline")),
    );
  });

  it("never reuses an id between the wide and outline variants", () => {
    const ids = [
      ...REQUEST_PATH.map((id) => stageAnchor(id)),
      ...REQUEST_PATH.map((id) => stageAnchor(id, "outline")),
    ];
    expect(new Set(ids).size).toBe(ids.length);
  });
});
