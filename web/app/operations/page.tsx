import type { Metadata } from "next";
import { LiveOperations } from "@/components/live-operations";
import { measureGatewayHealth } from "@/lib/gateway-health";
import { fetchGatewayProbe } from "@/lib/gateway-probe";
import { fetchCalibrationHealth, fetchRecentTraces } from "@/lib/overview-data";

export const metadata: Metadata = {
  title: "Live Operations | Fin-Sentry",
};

export default async function OperationsPage() {
  const [calibration, recent, health, probe] = await Promise.all([
    fetchCalibrationHealth(),
    fetchRecentTraces(1),
    measureGatewayHealth(),
    fetchGatewayProbe(),
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
