/** Relative age of an ISO timestamp, e.g. "just now", "12m ago", "3d ago". */
export function relativeTime(iso: string, now: number = Date.now()): string {
  const diffMs = now - new Date(iso).getTime();
  const minutes = Math.round(diffMs / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

/** A fixed, timezone-explicit UTC stamp, e.g. "Oct 4, 17:11 UTC". Used for
 * persisted readings so the string is identical on server and client. */
export function formatUtc(iso: string): string {
  const d = new Date(iso);
  const month = d.toLocaleString("en-US", { month: "short", timeZone: "UTC" });
  const hh = String(d.getUTCHours()).padStart(2, "0");
  const mm = String(d.getUTCMinutes()).padStart(2, "0");
  return `${month} ${d.getUTCDate()}, ${hh}:${mm} UTC`;
}

/** First eight characters of a trace id: enough to recognize, short enough
 * for a dense table. The full id is always available on copy and in detail. */
export function shortId(id: string): string {
  return id.slice(0, 8);
}

/** UTC stamp with seconds for dense tables, e.g. "Oct 6, 02:26:21". The
 * zone is named once in the column header, not repeated on every row. */
export function formatUtcSeconds(iso: string): string {
  const d = new Date(iso);
  const month = d.toLocaleString("en-US", { month: "short", timeZone: "UTC" });
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${month} ${d.getUTCDate()}, ${pad(d.getUTCHours())}:${pad(d.getUTCMinutes())}:${pad(d.getUTCSeconds())}`;
}
