"use client";

import { useState } from "react";
import {
  ConfidenceChip,
  HypothesisStatusBadge,
  PredictionBadge,
  RecordChip,
  SubsystemChip,
} from "@/components/incidents/badges";
import { defaultHypothesis, missingFor, rivalsOf } from "@/lib/agent-view";
import {
  hypothesisRows,
  signalLabel,
  type Detail,
  type EvidenceRef,
  type HypothesisRow,
  type HypothesisStatus,
  type Origin,
  type PredictionResult,
} from "@/lib/incidents";
import { useIsDesktop } from "@/lib/use-is-desktop";

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
            className="text-accent inline-flex min-h-11 min-w-11 items-center justify-center font-mono underline underline-offset-4"
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

function Records({
  title,
  empty,
  refs,
  origin,
  tone,
}: {
  title: string;
  empty: string;
  refs: EvidenceRef[];
  origin: Origin;
  tone: string;
}) {
  const records = refs.filter((r) => r.kind !== "query_result");
  return (
    <section
      className="border-border rounded-lg border border-l-2 p-4"
      style={{ borderLeftColor: tone }}
    >
      <h4 className="text-text-primary text-base font-medium">
        {title} ({records.length})
      </h4>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {records.length === 0 ? (
          <span className="text-text-secondary text-base">{empty}</span>
        ) : (
          records.map((r) => (
            <RecordChip
              key={`${r.kind}:${r.record_id}`}
              record={r}
              origin={origin}
            />
          ))
        )}
      </div>
    </section>
  );
}

/** One hypothesis laid open: what supports it, what cuts against it, what was wanted and not
 * had, and the rivals it was weighed against. The four are kept apart on purpose. Missing
 * evidence is a prediction no record settled, which is not the same as counter-evidence. */
function HypothesisFile({
  row,
  rows,
  origin,
  onPick,
}: {
  row: HypothesisRow;
  rows: HypothesisRow[];
  origin: Origin;
  onPick: (id: string) => void;
}) {
  const missing = missingFor(row);
  const rivals = rivalsOf(rows, row.hypothesis_id);
  return (
    <div className="space-y-4">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <SubsystemChip subsystem={row.subsystem} />
          <HypothesisStatusBadge status={row.status} />
          {row.confidence ? (
            <ConfidenceChip confidence={row.confidence} />
          ) : null}
        </div>
        <p className="text-text-primary mt-3 text-lg leading-snug text-pretty">
          {row.statement}
        </p>
        <p className="text-text-secondary mt-2 text-base leading-relaxed">
          <span className="text-text-tertiary">Why it stands here: </span>
          {row.why}
        </p>
        {row.status === "supported" ? (
          <p className="text-text-tertiary mt-1 text-base sm:text-sm">
            Supported is not proven. The records are consistent with it.
          </p>
        ) : null}
      </div>

      <div className="grid gap-3 xl:grid-cols-2">
        <Records
          title="Supporting evidence"
          empty="No record supports it."
          refs={row.supporting}
          origin={origin}
          tone="var(--info)"
        />
        <Records
          title="Counter-evidence"
          empty="No record cuts against it."
          refs={row.contradicting}
          origin={origin}
          tone="var(--failure)"
        />
      </div>

      <section className="border-warning/50 rounded-lg border border-dashed p-4">
        <h4 className="text-text-primary text-base font-medium">
          Missing evidence ({missing.length})
        </h4>
        {missing.length === 0 ? (
          <p className="text-text-secondary mt-1 text-base">
            Every prediction of this hypothesis was settled by a record.
          </p>
        ) : (
          <ul className="mt-2 space-y-2">
            {missing.map((m, i) => (
              <li key={i} className="text-text-secondary text-base">
                <span className="text-text-primary">
                  {m.kind === "unchecked"
                    ? "Could not be checked: "
                    : "Expected and not found: "}
                </span>
                {m.prediction.description}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section className="border-border rounded-lg border p-4">
        <h4 className="text-text-primary text-base font-medium">
          Rival explanations ({rivals.length})
        </h4>
        {rivals.length === 0 ? (
          <p className="text-text-secondary mt-1 text-base">
            {row.symptom === null
              ? "The session stored no symptom for this hypothesis, so its rivals cannot be named."
              : "No other hypothesis explains the same symptom."}
          </p>
        ) : (
          <ul className="mt-2 space-y-1">
            {rivals.map((r) => (
              <li
                key={r.hypothesis_id}
                className="flex flex-wrap items-center gap-2"
              >
                <button
                  type="button"
                  onClick={() => onPick(r.hypothesis_id)}
                  className="text-accent inline-flex min-h-11 min-w-11 items-center font-mono text-base underline underline-offset-4"
                >
                  {r.hypothesis_id}
                </button>
                <HypothesisStatusBadge status={r.status} />
                <span className="text-text-secondary text-base">{r.why}</span>
              </li>
            ))}
          </ul>
        )}
        {row.set_aside.map((line, i) => (
          <p
            key={i}
            className="border-warning/40 text-text-secondary mt-2 rounded-md border border-dashed p-3 text-base"
          >
            Set aside: {line}.
          </p>
        ))}
      </section>

      {row.predictions.length > 0 ? (
        <details className="group">
          <summary className="text-accent hover:text-text-primary inline-flex min-h-11 cursor-pointer items-center gap-2 text-sm underline-offset-4 group-open:underline">
            Predictions and how each was judged ({row.predictions.length})
          </summary>
          <ul className="mt-2">
            {row.predictions.map((p, i) => (
              <Prediction key={`${p.signal}-${i}`} p={p} />
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}

/**
 * The competing hypotheses side by side. The list is in the order the report ranks them, each
 * row stating where it stands. Selecting one brings it forward and opens it in full: the
 * records for it, the records against it, the evidence that was wanted and not had, and its
 * rivals. The leader opens first. Rank, status and the records are stored. The sentence on why
 * a hypothesis stands where it does is derived from its stored predictions and says nothing
 * the investigator did not record.
 */
export function HypothesisLedger({ detail }: { detail: Detail }) {
  const rows = hypothesisRows(detail);
  const desktop = useIsDesktop();
  const [chosen, setChosen] = useState<string | null>(null);
  const initial = defaultHypothesis(rows);
  const current =
    rows.find((r) => r.hypothesis_id === chosen) ??
    (desktop ? rows.find((r) => r.hypothesis_id === initial) : undefined);
  const open = (id: string) =>
    setChosen((cur) => (cur === id && !desktop ? null : id));
  const detailFor = (row: HypothesisRow) => (
    <HypothesisFile
      row={row}
      rows={rows}
      origin={detail.origin}
      onPick={(id) => setChosen(id)}
    />
  );

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
          : "Hypotheses that explain the same symptom are rivals. The planner proposed each as structured predictions, and code, not the model, decided whether the retrieved records met them. Select one to read it against its evidence and its rivals."}
      </p>
      {rows.length > 0 ? (
        <div className="mt-4 grid gap-6 lg:grid-cols-[minmax(0,0.9fr)_minmax(0,1.3fr)] lg:items-start">
          <ol className="border-border border-t">
            {rows.map((row) => {
              const isOpen = current?.hypothesis_id === row.hypothesis_id;
              const quiet = current !== undefined && !isOpen;
              return (
                <li
                  key={row.hypothesis_id}
                  id={row.hypothesis_id}
                  data-selected={isOpen ? "true" : undefined}
                  className={`border-border relative scroll-mt-32 border-b transition-opacity duration-[var(--dur-base)] ${quiet ? "opacity-70 hover:opacity-100 focus-within:opacity-100" : ""}`}
                >
                  <span
                    aria-hidden="true"
                    className="absolute top-4 bottom-4 left-0 w-0.5 rounded-full"
                    style={{
                      background: RAIL[row.status],
                      opacity: isOpen || row.leading ? 1 : 0.5,
                    }}
                  />
                  <button
                    type="button"
                    aria-pressed={isOpen}
                    onClick={() => open(row.hypothesis_id)}
                    className={`block min-h-11 w-full py-4 pr-3 pl-5 text-left ${isOpen ? "bg-surface" : "hover:bg-surface-hover"}`}
                  >
                    <span className="flex flex-wrap items-center gap-2">
                      <span className="tabular-metric text-text-primary text-lg font-semibold">
                        {row.rank === null ? "Unranked" : `Rank ${row.rank}`}
                      </span>
                      <span className="text-text-tertiary font-mono text-sm">
                        {row.hypothesis_id}
                      </span>
                      <HypothesisStatusBadge status={row.status} />
                    </span>
                    <span className="text-text-primary mt-2 line-clamp-2 block text-base leading-snug">
                      {row.statement}
                    </span>
                    <span className="text-text-secondary mt-1 block text-base leading-snug">
                      {row.why}
                    </span>
                  </button>
                  {isOpen && !desktop ? (
                    <div className="swap-in border-border border-t px-4 py-5">
                      {detailFor(row)}
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ol>
          {desktop && current ? (
            <div
              key={current.hypothesis_id}
              style={{ ["--tone" as string]: RAIL[current.status] }}
              className="instrument swap-in bg-background-elevated/60 rounded-xl p-6"
            >
              {detailFor(current)}
            </div>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
