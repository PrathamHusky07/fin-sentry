interface MetricTileProps {
  label: string;
  value: string | number | null;
  unit?: string;
  stale: boolean;
  asOf: string | null;
}

/**
 * One metric value with its own staleness, never collapsed into a single
 * global "live" indicator (see finsentry/events/metrics_snapshot.py --
 * freshness is per-section because the sections come from different Kafka
 * topics with different update cadences).
 */
export function MetricTile({
  label,
  value,
  unit,
  stale,
  asOf,
}: MetricTileProps) {
  return (
    <div className="border-border bg-background-elevated rounded-md border p-4">
      <div className="text-text-secondary text-xs tracking-wide uppercase">
        {label}
      </div>
      <div
        className={`tabular-metric mt-1 text-2xl font-semibold ${stale ? "text-text-secondary" : "text-text-primary"}`}
      >
        {value === null ? "—" : value}
        {value !== null && unit ? (
          <span className="ml-1 text-base font-normal">{unit}</span>
        ) : null}
      </div>
      <div className="text-text-secondary mt-1 text-xs">
        {stale ? "Stale" : "Fresh"}
        {asOf ? ` · as of ${new Date(asOf).toLocaleTimeString()}` : ""}
      </div>
    </div>
  );
}
