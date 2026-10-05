import type { Metadata } from "next";
import { LiveOperations } from "@/components/live-operations";

export const metadata: Metadata = {
  title: "Live Operations — Fin-Sentry",
};

export default function OperationsPage() {
  return <LiveOperations />;
}
