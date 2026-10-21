import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { StageCards, stageHref } from "@/components/stage-cards";
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
  const titles = ["Guard", "Retrieve", "Generate", "Judge", "Agent"];

  it("sends Guard, Retrieve and Generate to their own request-path stage", () => {
    // The server render carries the narrow outline ids, the ones a phone shows.
    expect(hrefOf(markup, "Guard")).toBe("/architecture#stage-input-outline");
    expect(hrefOf(markup, "Retrieve")).toBe(
      "/architecture#stage-retrieval-outline",
    );
    expect(hrefOf(markup, "Generate")).toBe(
      "/architecture#stage-generation-outline",
    );
  });

  it("picks the wide id on a wide viewport, where the outline id is not displayed", () => {
    expect(stageHref({ stage: "input" }, true)).toBe(
      "/architecture#stage-input",
    );
    expect(stageHref({ stage: "retrieval" }, false)).toBe(
      "/architecture#stage-retrieval-outline",
    );
    expect(stageHref({ href: "/agent" }, true)).toBe("/agent");
  });

  it("sends Judge to the evaluation plane and Agent to the Agent route", () => {
    expect(hrefOf(markup, "Judge")).toBe("/architecture#evaluation-plane");
    expect(hrefOf(markup, "Agent")).toBe("/agent");
    expect(markup).not.toContain(">Investigate<");
  });

  it("points every in-page target at an id that exists on the architecture page", () => {
    const outlineAnchors = LAYERS.find(
      (l) => l.id === "request-path",
    )!.outline.flatMap((lane) => lane.steps.map((s) => s.anchor));
    for (const stage of ["input", "retrieval", "generation"] as const) {
      expect(outlineAnchors).toContain(stageAnchor(stage, "outline"));
      expect(REQUEST_PATH).toContain(stage);
    }
    expect(LAYERS.map((l) => l.id)).toContain("evaluation-plane");
  });

  it("never gives two cards the same destination", () => {
    const hrefs = titles.map((t) => hrefOf(markup, t));
    expect(new Set(hrefs).size).toBe(hrefs.length);
  });

  it("offers Red Team as a separate line that is not one of the numbered stages", () => {
    const [stages, rest] = markup.split("</ol>");
    expect(stages).not.toContain('href="/red-team"');
    expect(rest).toContain('href="/red-team"');
    expect(rest).toContain("Outside the request path.");
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
