import type { Metadata } from "next";
import { RouteStub } from "@/components/route-stub";

export const metadata: Metadata = {
  title: "Judge Panel — Fin-Sentry",
};

export default function JudgesPage() {
  return (
    <RouteStub
      title="Judge Panel"
      description="A searchable table of evaluated requests with flash-tier scores, frontier-tier evidence from real judges, and drift status against the calibration benchmark."
      reason="Day 9 work. It will show only what the backend actually persists -- real per-judge evidence identified by judge_id, never positional array indexing, and never a fabricated three-model ensemble where only one real judge ran."
    />
  );
}
