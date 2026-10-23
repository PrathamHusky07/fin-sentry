import { GATEWAY_URL } from "@/lib/config";

/** Mirrors GatewayProbeRun in finsentry/observability/gateway_probe.py field for field. */
export interface GatewayProbeRun {
  measured_at: string;
  target: string;
  samples: number;
  median_ms: number;
  p95_ms: number;
  max_ms: number;
}

/** The newest stored probe run. `latest` is null before the first run was recorded. */
export interface GatewayProbeSummary {
  latest: GatewayProbeRun | null;
  runs_recorded: number;
}

/**
 * The newest recorded gateway round-trip probe. It is a stored reading, so it is still there
 * when nothing has run since, and the page dates it. Null when the gateway or its store did
 * not answer, which the page shows as unavailable and never as a missing run.
 */
export async function fetchGatewayProbe(): Promise<GatewayProbeSummary | null> {
  try {
    const res = await fetch(`${GATEWAY_URL}/ops/gateway-probe/latest`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
    });
    if (!res.ok) return null;
    return (await res.json()) as GatewayProbeSummary;
  } catch {
    return null;
  }
}

/** A short millisecond figure: two decimals under 10 ms, one decimal under 100, then whole. */
export function formatMs(ms: number): string {
  if (ms < 10) return ms.toFixed(2);
  if (ms < 100) return ms.toFixed(1);
  return String(Math.round(ms));
}

/** True when the probe target is on the machine that ran it, so the figure holds no network distance. */
export function isLoopbackTarget(target: string): boolean {
  try {
    const host = new URL(target).hostname;
    return host === "localhost" || host === "127.0.0.1" || host === "[::1]";
  } catch {
    return false;
  }
}
