import type { Metadata } from "next";
import { JudgePanel } from "@/components/judge-panel";

export const metadata: Metadata = {
  title: "Judge Panel — Fin-Sentry",
};

export default function JudgesPage() {
  return <JudgePanel />;
}
