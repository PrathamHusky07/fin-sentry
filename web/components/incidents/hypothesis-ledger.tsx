import {
  ConfidenceChip,
  HypothesisStatusBadge,
  PredictionBadge,
  RecordChip,
  SubsystemChip,
} from "@/components/incidents/badges";
import {
  hypothesisRows,
  signalLabel,
  type Detail,
  type HypothesisRow,
  type HypothesisStatus,
  type Origin,
  type PredictionResult,
} from "@/lib/incidents";

const RAIL: Record<HypothesisStatus, string> = {
  supported: "var(--info)",
  open: "var(--text-tertiary)",
  weakened: "var(--warning)",
  refuted: "var(--failure)",
};

function QueryLinks({ ids }: { ids: string[] }) {
  if (ids.length === 0) {
    return <span className="text-text-tertiary">No query judged it</span>;
  }
  return (
    <span>
      Judged by{" "}
      {ids.map((id, i) => (
        <span key={id}>
          {i > 0 ? ", " : ""}
          <a
            href={`#${id}`}
            className="text-accent inline-flex min-h-11 items-center font-mono underline underline-offset-4"
          >
            {id}
          </a>
        </span>
      ))}
    </span>
  );
}

function Prediction({ p }: { p: PredictionResult }) {
  return (
    <li className="border-border grid gap-2 border-t py-3 first:border-t-0 sm:grid-cols-[minmax(0,1fr)_auto] sm:gap-x-6">
      <div className="min-w-0">
        <p className="text-text-primary text-base">
          Expected {p.expect ? "present" : "absent"}: {signalLabel(p.signal)}
          {p.subject ? (
            <span className="text-text-secondary"> (for {p.subject})</span>
          ) : null}
        </p>
        <p className="text-text-secondary mt-1 text-base leading-relaxed">
          {p.detail}
        </p>
        {p.restates_trigger ? (
          <p className="text-text-tertiary mt-1 text-sm">
            This signal restates the symptom that triggered the investigation,
            so seeing it shows the incident exists and says nothing about why.
          </p>
        ) : null}
        <p className="text-text-secondary mt-1 text-sm">
          <QueryLinks ids={p.query_ids} />
        </p>
      </div>
      <div className="sm:pt-0.5">
        <PredictionBadge state={p.state} />
      </div>
    </li>
  );
}

function Row({ row, origin }: { row: HypothesisRow; origin: Origin }) {
  const support = row.supporting.filter((r) => r.kind !== "query_result");
  const against = row.contradicting.filter((r) => r.kind !== "query_result");
  return (
    <li
      id={row.hypothesis_id}
      className="border-border relative scroll-mt-32 border-b py-6 pl-5 last:border-b-0"
    >
      <span
        aria-hidden="true"
        className="absolute top-6 bottom-6 left-0 w-0.5 rounded-full"
        style={{
          background: RAIL[row.status],
          opacity: row.leading ? 1 : 0.55,
        }}
      />
      <div className="flex flex-wrap items-center gap-2">
        <span className="tabular-metric text-text-primary text-lg font-semibold">
          {row.rank === null ? "Unranked" : `Rank ${row.rank}`}
        </span>
        <span className="text-text-tertiary font-mono text-sm">
          {row.hypothesis_id}
        </span>
        <SubsystemChip subsystem={row.subsystem} />
        <HypothesisStatusBadge status={row.status} />
        {row.confidence ? <ConfidenceChip confidence={row.confidence} /> : null}
      </div>
      <p className="text-text-primary mt-3 max-w-4xl text-base leading-relaxed">
        {row.statement}
      </p>
      <p className="text-text-secondary mt-2 max-w-4xl text-base leading-relaxed">
        <span className="text-text-tertiary">Why it stands here: </span>
        {row.why}
      </p>

      <div className="mt-4 grid gap-4 lg:grid-cols-2">
        <div>
          <p className="text-text-tertiary text-sm">
            Supporting records ({support.length})
          </p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {support.length === 0 ? (
              <span className="text-text-secondary text-base">
                No record supports it.
              </span>
            ) : (
              support.map((r) => (
                <RecordChip
                  key={`${r.kind}:${r.record_id}`}
                  record={r}
                  origin={origin}
                />
              ))
            )}
          </div>
        </div>
        <div>
          <p className="text-text-tertiary text-sm">
            Contradicting records ({against.length})
          </p>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {against.length === 0 ? (
              <span className="text-text-secondary text-base">
                No record cuts against it.
              </span>
            ) : (
              against.map((r) => (
                <RecordChip
                  key={`${r.kind}:${r.record_id}`}
                  record={r}
                  origin={origin}
                />
              ))
            )}
          </div>
        </div>
      </div>

      {row.predictions.length > 0 || row.set_aside.length > 0 ? (
        <details className="group mt-4">
          <summary className="text-accent hover:text-text-primary inline-flex min-h-11 cursor-pointer items-center gap-2 text-sm underline-offset-4 group-open:underline">
            Predictions and how each was judged ({row.predictions.length})
          </summary>
          <ul className="mt-2">
            {row.predictions.map((p, i) => (
              <Prediction key={`${p.signal}-${i}`} p={p} />
            ))}
          </ul>
          {row.set_aside.map((line, i) => (
            <p
              key={i}
              className="border-warning/40 text-text-secondary mt-2 rounded-md border border-dashed p-3 text-base"
            >
              Set aside: {line}.
            </p>
          ))}
        </details>
      ) : null}
    </li>
  );
}

/** The competing hypotheses in the order the report ranks them, each with the records that
 * support and contradict it and the predictions that moved its status. Rank, status and the
 * records are stored. The sentence on why a hypothesis stands where it does is derived from
 * its stored prediction results and says nothing the investigator did not record. */
export function HypothesisLedger({ detail }: { detail: Detail }) {
  const rows = hypothesisRows(detail);
  return (
    <section
      id="hypotheses"
      aria-labelledby="hypotheses-heading"
      className="scroll-mt-32"
    >
      <h2
        id="hypotheses-heading"
        className="text-text-primary text-2xl font-semibold tracking-tight"
      >
        Competing hypotheses
      </h2>
      <p className="text-text-secondary mt-2 max-w-3xl text-base leading-relaxed">
        {rows.length === 0
          ? "The investigator did not reach the point of holding hypotheses, so there is no ledger to show."
          : "Hypotheses that explain the same symptom are rivals. Each was proposed by the planner as structured predictions, and code, not the model, decided whether the retrieved records met them."}
      </p>
      {rows.length > 0 ? (
        <ol className="border-border mt-4 border-t">
          {rows.map((row) => (
            <Row key={row.hypothesis_id} row={row} origin={detail.origin} />
          ))}
        </ol>
      ) : null}
    </section>
  );
}
