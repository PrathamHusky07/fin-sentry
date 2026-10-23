/**
 * Archive timestamps are Python isoformat strings with a +00:00 suffix, and some drop trailing
 * zeros from the fraction. The gateway sends the same instants through pydantic, which writes a
 * trailing Z, six fraction digits, and no fraction at all on a whole second. Only the spelling
 * is changed here, never the instant.
 */
export function utcZ(iso: string): string {
  const m = /^(.*?)(?:\.(\d+))?(?:\+00:00|Z)$/.exec(iso);
  if (m === null) return iso;
  const fraction = (m[2] ?? "").padEnd(6, "0");
  return /^0*$/.test(fraction) ? `${m[1]}Z` : `${m[1]}.${fraction}Z`;
}

export function utcZOrNull(iso: string | null): string | null {
  return iso === null ? null : utcZ(iso);
}

/** Microseconds since the epoch, so two stored instants closer than a millisecond still order
 * the way the database ordered them. */
export function micros(iso: string): number {
  const ms = Date.parse(iso);
  if (Number.isNaN(ms)) throw new Error(`not a timestamp: ${iso}`);
  const fraction = /\.(\d+)/.exec(iso)?.[1] ?? "";
  const sub = Number(fraction.padEnd(6, "0").slice(3, 6));
  return ms * 1000 + sub;
}

/** The start of the UTC minute an instant falls in, as epoch milliseconds. */
export function minuteStart(iso: string): number {
  return Math.floor(Date.parse(iso) / 60_000) * 60_000;
}
