import type { Metadata } from "next";
import { Suspense } from "react";
import { RedTeamConsole } from "@/components/red-team-console";

export const metadata: Metadata = {
  title: "Red Team | Fin-Sentry",
};

export default function RedTeamPage() {
  return (
    <Suspense fallback={null}>
      <RedTeamConsole />
    </Suspense>
  );
}
