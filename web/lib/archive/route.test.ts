import { afterEach, describe, expect, it, vi } from "vitest";

const ROUTE = "@/app/api/archive/[...path]/route";

function context(path: string[]) {
  return { params: Promise.resolve({ path }) } as never;
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.resetModules();
});

describe("the archive route handler", () => {
  it("exports GET only, so a POST is refused by the framework", async () => {
    const route = await import(ROUTE);
    expect(Object.keys(route)).toEqual(["GET"]);
  });

  it("serves nothing when archived mode is off", async () => {
    vi.stubEnv("NEXT_PUBLIC_ARCHIVE_MODE", "");
    vi.resetModules();
    const { GET } = await import(ROUTE);
    const res = await GET(
      new Request("http://x/api/archive/traces"),
      context(["traces"]),
    );
    expect(res.status).toBe(404);
    expect(await res.json()).toEqual({
      error: "archived evidence is not enabled",
    });
  });

  it("serves the archived record when archived mode is on", async () => {
    vi.stubEnv("NEXT_PUBLIC_ARCHIVE_MODE", "true");
    vi.resetModules();
    const { GET } = await import(ROUTE);
    const res = await GET(
      new Request("http://x/api/archive/redteam/runs?limit=1"),
      context(["redteam", "runs"]),
    );
    expect(res.status).toBe(200);
    const runs = (await res.json()) as { run_id: string }[];
    expect(runs.map((r) => r.run_id)).toEqual([
      "49de39e1-e858-4b64-b661-bf766172f550",
    ]);
  });
});
