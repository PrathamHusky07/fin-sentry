/**
 * Archived-evidence mode: the site serves a read-only copy of recorded evidence from
 * docs/demo-archive instead of calling a live gateway. It is switched on by one explicit build
 * value and never by a failed gateway call, so an outage can never pass for an archived session.
 *
 * NEXT_PUBLIC_ so the browser bundle and the server agree. Both are fixed at build time.
 */
export const ARCHIVE_MODE: boolean =
  process.env.NEXT_PUBLIC_ARCHIVE_MODE === "true";

/** The one line every archived page carries, in two parts so the lead can be set heavier. */
export const ARCHIVE_NOTICE_LEAD = "Archived evidence.";
export const ARCHIVE_NOTICE_BODY =
  "This is a recorded copy of real runs, not a live system. Every record keeps its original time.";

/** The routes whose data comes from the archive. The landing and architecture pages are static. */
export const ARCHIVE_ROUTES = [
  "/overview",
  "/operations",
  "/investigations",
  "/generation",
  "/agent",
  "/red-team",
] as const;

/** Shown in place of any control that would start work. */
export const ARCHIVE_READ_ONLY =
  "This site shows archived evidence and is not connected to a live system, so nothing can be started here.";
