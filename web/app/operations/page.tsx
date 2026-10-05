import type { Metadata } from "next";
import { LiveOperations } from "@/components/live-operations";
import { fetchOverviewData } from "@/lib/overview-data";

export const metadata: Metadata = {
  title: "Live Operations — Fin-Sentry",
};

export default async function OperationsPage() {
  const overviewData = await fetchOverviewData();
  return <LiveOperations overviewData={overviewData} />;
}
