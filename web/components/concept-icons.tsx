/**
 * The seven concepts of the Fin-Sentry visual language, each with one
 * hand-drawn glyph on a 24 unit grid: guard, retrieve, generate, judge,
 * calibrate, investigate and MCP. The glyphs are strokes only so they take
 * their color from the surrounding tone. Used by the landing constellation
 * and the five stage cards; decorative, never data.
 */
export type ConceptId =
  | "guard"
  | "retrieve"
  | "generate"
  | "judge"
  | "calibrate"
  | "investigate"
  | "mcp";

/** The glyph as SVG children, to be placed inside any 24 unit viewBox. */
export function ConceptGlyph({ id }: { id: ConceptId }) {
  switch (id) {
    case "guard":
      return (
        <>
          <path d="M12 3l7 3v5.5c0 4.2-2.8 7.6-7 9.5-4.2-1.9-7-5.3-7-9.5V6l7-3z" />
          <path d="M8.9 12.1l2.2 2.2 4.1-4.4" />
        </>
      );
    case "retrieve":
      return (
        <>
          <circle cx="10.5" cy="10.5" r="5.75" />
          <path d="M15 15l5.5 5.5" />
          <path d="M8 9.5h5M8 12h3" />
        </>
      );
    case "generate":
      return (
        <>
          <path d="M11 3.5l1.9 5.2 5.2 1.9-5.2 1.9L11 17.7l-1.9-5.2L3.9 10.6l5.2-1.9L11 3.5z" />
          <path d="M18.5 15.5l.8 2.2 2.2.8-2.2.8-.8 2.2-.8-2.2-2.2-.8 2.2-.8.8-2.2z" />
        </>
      );
    case "judge":
      return (
        <>
          <path d="M12 4v16M7.5 20h9M5 7.5h14" />
          <path d="M5 7.5L2.5 13.2a2.75 2.75 0 0 0 5 0L5 7.5zM19 7.5l-2.5 5.7a2.75 2.75 0 0 0 5 0L19 7.5z" />
        </>
      );
    case "calibrate":
      return (
        <>
          <path d="M4.4 17a8.25 8.25 0 1 1 15.2 0" />
          <path d="M12 15l3.6-5.2" />
          <circle cx="12" cy="15" r="1.1" />
          <path d="M5.2 12.6l1.3.5M8.4 7.9l.9 1.1M12 6.4v1.5M15.6 7.9l-.9 1.1" />
        </>
      );
    case "investigate":
      return (
        <>
          <path d="M4 8V5.5A1.5 1.5 0 0 1 5.5 4H8M16 4h2.5A1.5 1.5 0 0 1 20 5.5V8M20 16v2.5a1.5 1.5 0 0 1-1.5 1.5H16M8 20H5.5A1.5 1.5 0 0 1 4 18.5V16" />
          <circle cx="12" cy="12" r="3.2" />
          <path d="M12 8.8V6.5M12 17.5v-2.3" />
        </>
      );
    case "mcp":
      return (
        <>
          <circle cx="12" cy="12" r="2.6" />
          <circle cx="4.6" cy="12" r="1.7" />
          <circle cx="18.4" cy="5.8" r="1.7" />
          <circle cx="18.4" cy="18.2" r="1.7" />
          <path d="M6.3 12h3.1M14 10.6l3.1-3.4M14 13.4l3.1 3.4" />
        </>
      );
  }
}

/** A standalone icon for HTML contexts. */
export function ConceptIcon({
  id,
  className = "h-5 w-5",
}: {
  id: ConceptId;
  className?: string;
}) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.6"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      className={className}
    >
      <ConceptGlyph id={id} />
    </svg>
  );
}
