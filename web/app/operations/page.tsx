import type { Metadata } from "next";
import { LiveOperations } from "@/components/live-operations";
import { ARCHIVE_MODE } from "@/lib/archive-mode";
import { measureGatewayHealth } from "@/lib/gateway-health";
import { fetchGatewayProbe } from "@/lib/gateway-probe";
import { serverOpsFetch } from "@/lib/ops-fetch-server";
import { fetchCalibrationHealth, fetchRecentTraces } from "@/lib/overview-data";

export const metadata: Metadata = {
  title: "Live Operations | Fin-Sentry",
};

// Read on every request. Relative phrases such as "the newest 21h ago" are measured from now,
// and a page rendered once at build time would freeze them.
export const dynamic = "force-dynamic";

export default async function OperationsPage() {
  const [calibration, recent, health, probe] = await Promise.all([
    fetchCalibrationHealth(),
    fetchRecentTraces(1),
    // Archived evidence has no gateway to time, so the page's own check stays unmeasured. The
    // recorded probe is a stored row with its original date, so it is read in both modes.
    ARCHIVE_MODE ? null : measureGatewayHealth(),
    fetchGatewayProbe(serverOpsFetch),
  ]);
  return (
    <LiveOperations
      calibration={calibration}
      newest={recent?.[0] ?? null}
      health={health}
      probe={probe}
    />
  );
}
