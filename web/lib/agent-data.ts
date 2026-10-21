import { GATEWAY_URL } from "@/lib/config";
import type { Origin } from "@/lib/incidents";

/** The Amazon judge disagreement the landing page shows as a capture. Its live trace expired
 * from the event log, and this id is how the Agent page checks whether that is still true. */
export const AMAZON_TRACE_ID = "96bca4b5-f707-4a93-b421-2674032849b5";

export type LiveLookup = "available" | "unavailable" | "unknown";

/** Looks the trace up on the gateway, read only. "unavailable" means the gateway answered and
 * holds no such trace. "unknown" means the gateway could not be asked, which is not the same
 * thing, and the page says so. */
export async function lookupTrace(appTraceId: string): Promise<LiveLookup> {
  try {
    const res = await fetch(
      `${GATEWAY_URL}/ops/traces/${encodeURIComponent(appTraceId)}`,
      { cache: "no-store", signal: AbortSignal.timeout(4000) },
    );
    if (res.status === 404) return "unavailable";
    if (!res.ok) return "unknown";
    const body: unknown = await res.json();
    const found =
      typeof body === "object" && body !== null
        ? (body as Record<string, unknown>).found
        : undefined;
    if (found === true) return "available";
    return found === false ? "unavailable" : "unknown";
  } catch {
    return "unknown";
  }
}

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
    const res = await fetch(`${GATEWAY_URL}/ops/investigations?limit=50`, {
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
