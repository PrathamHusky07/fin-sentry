import type { Metadata } from "next";
import { LiveOperations } from "@/components/live-operations";
import { measureGatewayHealth } from "@/lib/gateway-health";
import {
  fetchCalibrationHealth,
  fetchRecentTraces,
  fetchThroughputHistory,
} from "@/lib/overview-data";

export const metadata: Metadata = {
  title: "Live Operations | Fin-Sentry",
};

export default async function OperationsPage() {
  const [calibration, recent, history, health] = await Promise.all([
    fetchCalibrationHealth(),
    fetchRecentTraces(1),
    fetchThroughputHistory(),
    measureGatewayHealth(),
  ]);
  return (
    <LiveOperations
      calibration={calibration}
      newest={recent?.[0] ?? null}
      history={history}
      health={health}
    />
  );
}
