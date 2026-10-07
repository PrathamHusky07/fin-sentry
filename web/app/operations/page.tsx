import type { Metadata } from "next";
import { LiveOperations } from "@/components/live-operations";
import { fetchCalibrationHealth, fetchRecentTraces } from "@/lib/overview-data";

export const metadata: Metadata = {
  title: "Live Operations — Fin-Sentry",
};

export default async function OperationsPage() {
  const [calibration, recent] = await Promise.all([
    fetchCalibrationHealth(),
    fetchRecentTraces(12),
  ]);
  return <LiveOperations calibration={calibration} recent={recent} />;
}
