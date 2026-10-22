import { GATEWAY_URL } from "@/lib/config";

/** One measurement of the gateway's health route, taken by the web server. */
export interface GatewayHealthCheck {
  /** Median round trip across the samples, in milliseconds. */
  medianMs: number;
  samples: number;
  /** When the measurement finished, as an ISO timestamp. */
  measuredAt: string;
}

export function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 === 1
    ? sorted[mid]
    : (sorted[mid - 1] + sorted[mid]) / 2;
}

interface Probe {
  fetchFn?: typeof fetch;
  /** Milliseconds from any fixed origin. Injected so a test can fix the durations. */
  clock?: () => number;
  samples?: number;
}

/**
 * Times a few real requests to the gateway's health route and reports the median. The route
 * runs no retrieval and no model, so this is the cost of reaching the gateway and nothing
 * more. It is a different quantity from the request latency in the metrics buckets, and the
 * page labels it that way. Null when any request fails, so a gateway that cannot be reached
 * shows "not measured" and never a fast-looking number.
 */
export async function measureGatewayHealth({
  fetchFn = fetch,
  clock = () => performance.now(),
  samples = 3,
}: Probe = {}): Promise<GatewayHealthCheck | null> {
  const durations: number[] = [];
  try {
    for (let i = 0; i < samples; i += 1) {
      const start = clock();
      const res = await fetchFn(`${GATEWAY_URL}/health`, {
        cache: "no-store",
        signal: AbortSignal.timeout(4000),
      });
      await res.arrayBuffer();
      const elapsed = clock() - start;
      if (!res.ok) return null;
      durations.push(elapsed);
    }
  } catch {
    return null;
  }
  return {
    medianMs: Math.round(median(durations) * 10) / 10,
    samples,
    measuredAt: new Date().toISOString(),
  };
}
