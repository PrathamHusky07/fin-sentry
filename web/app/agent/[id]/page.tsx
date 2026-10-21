import type { Metadata } from "next";
import { IncidentWorkspace } from "@/components/incidents/incident-workspace";

export const metadata: Metadata = {
  title: "Incident investigation | Fin-Sentry",
};

export default async function IncidentPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <IncidentWorkspace id={id} />;
}
