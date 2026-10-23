import { serverOpsFetch } from "@/lib/ops-fetch-server";
import demoRecord from "@/lib/demo-record.json";
import type { Origin } from "@/lib/incidents";

/** The configured demonstration disagreement (lib/demo-record.json). Today it is the Amazon
 * judge disagreement the landing page shows as a capture. Its live trace expired from the event
 * log, so the Agent page only links to the capture. */
export const AMAZON_TRACE_ID = demoRecord.disagreement.app_trace_id;

export interface StoredCounts {
  live: number;
  fixture: number;
  newestLive: string | null;
  newestFixture: string | null;
}

/** Counts the stored investigations by where they ran, from the same listing the explorer
 * reads. Null when the listing cannot be read, so the page shows "not readable" and never a
 * zero. Looks at the newest 50 only, and says so. */
export async function storedCounts(): Promise<StoredCounts | null> {
  try {
    const res = await serverOpsFetch("/ops/investigations?limit=50", {
      cache: "no-store",
      signal: AbortSignal.timeout(4000),
    });
    if (!res.ok) return null;
    const body: unknown = await res.json();
    const list =
      typeof body === "object" && body !== null
        ? (body as { investigations?: unknown }).investigations
        : undefined;
    if (!Array.isArray(list)) return null;
    const rows = list as { investigation_id: string; origin: Origin }[];
    const live = rows.filter((r) => r.origin === "live");
    const fixture = rows.filter((r) => r.origin === "fixture");
    return {
      live: live.length,
      fixture: fixture.length,
      newestLive: live[0]?.investigation_id ?? null,
      newestFixture: fixture[0]?.investigation_id ?? null,
    };
  } catch {
    return null;
  }
}
