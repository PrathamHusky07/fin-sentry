import type { ReactNode } from "react";

type Provenance =
  "PERSISTED" | "DERIVED" | "LIVE" | "HISTORICAL" | "PLANNED" | "NOT_AVAILABLE";

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
      <span className="border-warning/40 bg-warning/10 text-warning inline-flex w-fit items-center rounded-full border px-3 py-1 text-xs font-medium tracking-wide uppercase">
        {PROVENANCE_LABEL[provenance]}
      </span>
      <h1
        id="route-stub-heading"
        className="text-text-primary text-2xl font-semibold tracking-tight"
      >
        {title}
      </h1>
      <p className="text-text-primary text-base leading-relaxed">
        {description}
      </p>
      <p className="border-border text-text-secondary border-l-2 pl-4 text-sm">
        {reason}
      </p>
      {children}
    </section>
  );
}
