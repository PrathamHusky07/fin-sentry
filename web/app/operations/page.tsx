import type { Metadata } from "next";
import { LiveOperations } from "@/components/live-operations";
import {
  fetchCalibrationHealth,
  fetchRecentTraces,
  fetchThroughputHistory,
} from "@/lib/overview-data";

export const metadata: Metadata = {
  title: "Live Operations | Fin-Sentry",
};

export default async function OperationsPage() {
  const [calibration, recent, history] = await Promise.all([
    fetchCalibrationHealth(),
    fetchRecentTraces(1),
    fetchThroughputHistory(),
  ]);
  return (
    <LiveOperations
      calibration={calibration}
      newest={recent?.[0] ?? null}
      history={history}
    />
  );
}
