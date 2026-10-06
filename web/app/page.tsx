import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "Fin-Sentry",
};

/**
 * Day 9 Phase 4: information-architecture placeholder. The presentation
 * layer (hero, architecture visualization, project narrative) is built in
 * Phase 5 -- this exists only so the route split (operations tool moves to
 * /overview) lands as its own reviewable step, per web/CLAUDE.md's
 * application-vs-presentation split.
 */
export default function LandingPage() {
  return (
    <div className="mx-auto flex w-full max-w-5xl flex-1 flex-col items-start justify-center px-4 py-16 sm:px-6">
      <h1 className="text-text-primary text-3xl font-semibold tracking-tight">
        Fin-Sentry
      </h1>
      <p className="text-text-secondary mt-3 max-w-xl text-base">
        An AI reliability and evaluation platform for financial RAG. The
        presentation layer for this project is under construction.
      </p>
      <Link
        href="/overview"
        className="focus-visible:outline-accent border-border bg-background-elevated text-text-primary mt-6 inline-flex min-h-11 items-center rounded-md border px-4 text-sm font-medium hover:bg-surface focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2"
      >
        Open the operations console
      </Link>
    </div>
  );
}
