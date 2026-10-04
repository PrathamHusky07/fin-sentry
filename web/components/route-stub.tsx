import type { ReactNode } from "react";

type Provenance = "PERSISTED" | "DERIVED" | "LIVE" | "HISTORICAL" | "PLANNED" | "NOT_AVAILABLE";

export interface RouteStubProps {
  /** The route's operational name, e.g. "Live Operations". */
  title: string;
  /** One-sentence statement of what this route will show, once built. */
  description: string;
  /** Why it isn't built yet -- a real reason, never "coming soon". */
  reason: string;
  provenance?: Provenance;
  children?: ReactNode;
}

const PROVENANCE_LABEL: Record<Provenance, string> = {
  PERSISTED: "Persisted",
  DERIVED: "Derived",
  LIVE: "Live",
  HISTORICAL: "Historical",
  PLANNED: "Planned",
  NOT_AVAILABLE: "Not available",
};

/**
 * An honest placeholder for a route whose real implementation hasn't landed
 * yet. Never renders charts, tables, or sample data -- a stub route has
 * nothing persisted to show, and showing anything else would be fabricated.
 */
export function RouteStub({
  title,
  description,
  reason,
  provenance = "PLANNED",
  children,
}: RouteStubProps) {
  return (
    <section
      aria-labelledby="route-stub-heading"
      className="mx-auto flex max-w-2xl flex-1 flex-col justify-center gap-4 px-4 py-16 sm:px-6"
    >
      <span className="inline-flex w-fit items-center rounded-full border border-amber-600/40 bg-amber-500/10 px-3 py-1 text-xs font-medium tracking-wide text-amber-700 uppercase dark:border-amber-400/30 dark:text-amber-300">
        {PROVENANCE_LABEL[provenance]}
      </span>
      <h1 id="route-stub-heading" className="text-2xl font-semibold tracking-tight">
        {title}
      </h1>
      <p className="text-base leading-relaxed text-neutral-700 dark:text-neutral-300">
        {description}
      </p>
      <p className="border-l-2 border-neutral-300 pl-4 text-sm text-neutral-500 dark:border-neutral-700 dark:text-neutral-400">
        {reason}
      </p>
      {children}
    </section>
  );
}
