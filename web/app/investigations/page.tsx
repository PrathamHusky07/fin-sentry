import type { Metadata } from "next";
import { Suspense } from "react";
import { Investigations } from "@/components/investigations";

export const metadata: Metadata = {
  title: "Investigations | Fin-Sentry",
};

export default function InvestigationsPage() {
  return (
    <Suspense fallback={null}>
      <Investigations />
    </Suspense>
  );
}
