import type { Metadata } from "next";
import { LiveOperations } from "@/components/live-operations";
import { ARCHIVE_MODE } from "@/lib/archive-mode";
import { measureGatewayHealth } from "@/lib/gateway-health";
import { fetchGatewayProbe } from "@/lib/gateway-probe";
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
    // Archived evidence has no gateway to time, and no probe run is part of the archive.
    ARCHIVE_MODE ? null : measureGatewayHealth(),
    ARCHIVE_MODE ? null : fetchGatewayProbe(),
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
