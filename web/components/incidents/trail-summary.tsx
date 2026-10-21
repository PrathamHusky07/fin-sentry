import { QueryOutcomeBadge } from "@/components/incidents/badges";
import { citationTrace, queryTally, stoppedWhy } from "@/lib/agent-view";
import {
  STOPPING_LABEL,
  STOPPING_MEANING,
  type Detail,
  type QueryOutcome,
} from "@/lib/incidents";

const ORDER: QueryOutcome[] = [
  "returned",
  "verified_empty",
  "unverified_empty",
  "unavailable",
  "rejected",
];

function Tile({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="border-border bg-background-elevated/50 rounded-xl border p-4">
      <dt className="text-text-tertiary text-base sm:text-sm">{title}</dt>
      <dd className="mt-2 space-y-1.5">{children}</dd>
    </div>
  );
}

const TEXT = "text-text-secondary text-base leading-snug";

/**
 * The third layer in four readings before the detail: what the queries returned, whether
 * every citation traces to one, what the investigation used, and why it stopped. The counts are
 * derived from the stored timeline, and the citation check is re-run here against the stored
 * query records. The backend validates citations before it stores a report, so a mismatch
 * would mean the stored session and that check disagree, and the tile says so. Each tile says
 * "not stored" when its source was not stored, and never fills the gap.
 */
export function TrailSummary({ detail: d }: { detail: Detail }) {
  const tally = queryTally(d);
  const total = ORDER.reduce((n, k) => n + tally[k], 0);
  const trace = citationTrace(d);
  const why = stoppedWhy(d);
  const used = d.usage?.used;
  const max = d.usage?.budgets;
  return (
    <dl className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
      <Tile title="What the queries returned">
        {total === 0 ? (
          <p className={TEXT}>No query was stored.</p>
        ) : (
          ORDER.filter((k) => tally[k] > 0).map((k) => (
            <p key={k} className="flex items-center gap-2">
              <span className="tabular-metric text-text-primary w-6 text-right text-base">
                {tally[k]}
              </span>
              <QueryOutcomeBadge outcome={k} />
            </p>
          ))
        )}
      </Tile>
      <Tile title="Citation check">
        {trace === null ? (
          <p className={TEXT}>
            No report was stored, so nothing is cited and nothing was checked.
          </p>
        ) : trace.cited === 0 ? (
          <p className={TEXT}>
            The report cites no record. An abstention makes no claim.
          </p>
        ) : (
          <>
            <p className="text-text-primary text-base">
              <span className="tabular-metric">
                {trace.traced} of {trace.cited}
              </span>{" "}
              cited records trace to a query in this session.
            </p>
            <p className={TEXT}>
              {trace.untraced.length === 0
                ? "Each one was returned by a stored query, which is what the backend requires before it stores a report."
                : `${trace.untraced.length} could not be matched to a stored query: ${trace.untraced.map((r) => r.record_id).join(", ")}.`}
            </p>
          </>
        )}
      </Tile>
      <Tile title="Budget consumed">
        {used && max ? (
          <>
            <p className="text-text-primary text-base">
              <span className="tabular-metric">
                {used.tool_calls} of {max.max_tool_calls}
              </span>{" "}
              tool calls
            </p>
            <p className="text-text-primary text-base">
              <span className="tabular-metric">
                {used.inference_calls} of {max.max_inference_calls}
              </span>{" "}
              {d.origin === "fixture"
                ? "scripted planner calls"
                : "model calls"}
              {d.origin === "live" && d.usage
                ? `, $${d.usage.model.cost_usd.toFixed(4)} estimated`
                : ""}
            </p>
            {d.origin === "fixture" ? (
              <p className={TEXT}>
                A fixture replay. No model was called, and its clock is not a
                measurement.
              </p>
            ) : null}
          </>
        ) : (
          <p className={TEXT}>
            Not stored. A session that ends without a final state cannot say
            what it used.
          </p>
        )}
      </Tile>
      <Tile title="Why it stopped">
        {d.stopping_reason ? (
          <>
            <p className="text-text-primary text-base font-medium">
              {STOPPING_LABEL[d.stopping_reason]}
            </p>
            <p className={TEXT}>{why ?? STOPPING_MEANING[d.stopping_reason]}</p>
          </>
        ) : (
          <p className={TEXT}>
            It never reached a stop, so no reason was stored.
          </p>
        )}
      </Tile>
    </dl>
  );
}
