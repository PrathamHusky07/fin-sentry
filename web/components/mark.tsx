/** The Fin-Sentry mark: a sighting aperture. The outer ring is the request
 * boundary, the arc is the evaluation plane, and the dot is the single
 * point under observation. Purely a logo; it carries no data. */
/** The mark's shapes on a 32 unit grid, so the landing constellation can
 * draw the same identity at its center. */
export function MarkShapes() {
  return (
    <>
      <circle
        cx="16"
        cy="16"
        r="12.5"
        stroke="var(--text-primary)"
        strokeOpacity="0.9"
        strokeWidth="1.75"
      />
      <path
        d="M16 6.5a9.5 9.5 0 0 1 8.2 4.75"
        stroke="var(--signal)"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <path
        d="M3.5 16h5M23.5 16h5M16 3.5v5M16 23.5v5"
        stroke="var(--text-primary)"
        strokeOpacity="0.55"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
      <circle cx="16" cy="16" r="2.75" fill="var(--accent)" />
    </>
  );
}

export function Mark({ className = "h-6 w-6" }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 32 32"
      fill="none"
      aria-hidden="true"
      className={className}
    >
      <MarkShapes />
    </svg>
  );
}
