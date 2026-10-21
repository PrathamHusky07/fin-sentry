"use client";

import { Fragment, useState } from "react";
import { AsyncState, type AsyncStatus } from "@/components/async-state";
import {
  ExpectationChip,
  RedTeamOutcomeBadge,
  differenceText,
} from "@/components/red-team-badges";
import { formatUtcSeconds, shortId } from "@/lib/format";
import {
  CATEGORY_LABEL,
  CATEGORY_ORDER,
  CHANGE_LABEL,
  OUTCOMES,
  OUTCOME_LABEL,
  byScenario,
  expectedLabel,
  isSafetyBoundSkip,
  layerLabel,
  streakChanges,
  streaks,
  type Category,
  type Change,
  type ExecutionRecord,
  type Outcome,
  type RunRecord,
} from "@/lib/red-team";

export interface ResultFilters {
  category: Category | "";
  outcome: Outcome | "";
  runId: string;
}

const CONTROL =
  "w-full border-border-strong bg-background-elevated text-text-primary hover:border-line-active focus-visible:border-accent min-h-11 min-w-0 rounded-lg border px-3 text-base sm:text-sm";

interface LogRow {
  key: string;
  /** Oldest first. */
  executions: ExecutionRecord[];
  first: ExecutionRecord;
  last: ExecutionRecord;
  change: Change | null;
}

function rowTone(e: ExecutionRecord): string {
  if (e.outcome === "missed") return "var(--failure)";
  if (e.expectation === "not_met") return "var(--warning)";
  if (e.outcome === "caught") return "var(--positive)";
  return "var(--warning)";
}

function time(e: ExecutionRecord): number {
  return Date.parse(e.started_at ?? "") || Number.MAX_SAFE_INTEGER;
}

/** DERIVED. Executions after the filters, as log rows newest first. Grouped, consecutive
 * identical results of one scenario are one row. The change that led into a row is shown only
 * when no outcome or run filter is on, because a filter removes the executions between. */
function buildRows(
  executions: ExecutionRecord[],
  grouped: boolean,
  showChanges: boolean,
): LogRow[] {
  const rows: LogRow[] = [];
  if (!grouped) {
    for (const e of executions) {
      rows.push({
        key: e.execution_id,
        executions: [e],
        first: e,
        last: e,
        change: null,
      });
    }
  } else {
    for (const [, list] of byScenario(executions)) {
      const runs = streaks(list);
      const changes = streakChanges(runs);
      runs.forEach((s, i) =>
        rows.push({
          key: `${s.last.execution_id}`,
          executions: s.executions,
          first: s.first,
          last: s.last,
          change: showChanges ? changes[i] : null,
        }),
      );
    }
  }
  return rows.sort(
    (a, b) => time(b.last) - time(a.last) || b.last.seq - a.last.seq,
  );
}

function When({ row }: { row: LogRow }) {
  const f = (e: ExecutionRecord) =>
    e.started_at ? formatUtcSeconds(e.started_at) : "Queued";
  return row.executions.length === 1 ? (
    <>{f(row.last)}</>
  ) : (
    <>
      {f(row.last)}
      <span className="text-text-tertiary block">from {f(row.first)}</span>
    </>
  );
}

function Observed({ row }: { row: LogRow }) {
  const e = row.last;
  const diff = differenceText(e);
  return (
    <span className="flex flex-col items-start gap-1">
      <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <RedTeamOutcomeBadge
          outcome={e.outcome}
          state={e.state}
          safetyBound={isSafetyBoundSkip(e)}
        />
        {row.executions.length > 1 ? (
          <span className="text-text-primary text-base font-medium tabular-nums sm:text-sm">
            {row.executions.length} times
          </span>
        ) : null}
        {e.outcome === "caught" ? (
          <span className="text-text-secondary text-base sm:text-sm">
            {layerLabel(e.acting_layer)}
          </span>
        ) : null}
      </span>
      {diff ? (
        <span className="text-warning text-base leading-snug sm:text-sm">
          {diff}
        </span>
      ) : null}
    </span>
  );
}

function ScenarioCell({
  row,
  expanded,
  onToggle,
  onOpen,
}: {
  row: LogRow;
  expanded: boolean;
  onToggle: () => void;
  onOpen: (id: string) => void;
}) {
  const e = row.last;
  const many = row.executions.length > 1;
  const head = (
    <>
      <span className="text-text-primary text-base font-medium sm:text-sm">
        {e.scenario_id}, version {e.scenario_version}
      </span>
      <span className="text-text-tertiary hidden text-base lg:block lg:text-xs">
        {CATEGORY_LABEL[e.category]}
      </span>
    </>
  );
  return (
    <div>
      {many ? (
        <button
          type="button"
          aria-expanded={expanded}
          aria-label={`${expanded ? "Hide" : "Show"} the ${row.executions.length} executions of ${e.scenario_id}, version ${e.scenario_version}`}
          onClick={onToggle}
          className="flex min-h-11 w-full flex-col items-start justify-center rounded-md text-left"
        >
          {head}
        </button>
      ) : (
        <button
          type="button"
          onClick={() => onOpen(e.execution_id)}
          aria-label={`Open evidence for ${e.scenario_id}, run ${shortId(e.run_id)}`}
          className="flex min-h-11 w-full flex-col items-start justify-center rounded-md text-left"
        >
          {head}
        </button>
      )}
      {row.change ? (
        <span
          className={`mt-0.5 block text-base font-medium sm:text-sm ${row.change === "regression" || row.change === "lost_result" || row.change === "expectation_lost" ? "text-failure" : "text-text-secondary"}`}
        >
          {CHANGE_LABEL[row.change]}
        </span>
      ) : null}
      {many ? (
        <button
          type="button"
          onClick={() => onOpen(e.execution_id)}
          aria-label={`Open evidence for ${e.scenario_id}, run ${shortId(e.run_id)}`}
          className="text-accent min-h-11 text-base underline underline-offset-4 sm:text-sm"
        >
          Open the latest evidence
        </button>
      ) : null}
    </div>
  );
}

function Expanded({
  row,
  onOpen,
}: {
  row: LogRow;
  onOpen: (id: string) => void;
}) {
  return (
    <ul className="border-border bg-background-elevated/40 border-t px-3 py-2">
      {[...row.executions].reverse().map((e) => (
        <li
          key={e.execution_id}
          className="border-border flex flex-wrap items-center justify-between gap-2 border-b py-1 last:border-b-0"
        >
          <span className="text-text-secondary text-base tabular-nums sm:text-sm">
            {e.started_at ? `${formatUtcSeconds(e.started_at)} UTC` : "Queued"},
            run {shortId(e.run_id)}
          </span>
          <button
            type="button"
            onClick={() => onOpen(e.execution_id)}
            aria-label={`Open evidence for ${e.scenario_id}, run ${shortId(e.run_id)} at ${e.started_at ?? "queue"}`}
            className="text-accent min-h-11 min-w-11 text-base underline underline-offset-4 sm:text-sm"
          >
            Evidence
          </button>
        </li>
      ))}
    </ul>
  );
}

/**
 * Every stored execution as a log, newest first, with repeated identical results collapsed
 * into one row that says how many and when. A row that follows a different result says what
 * changed. The toggle shows one row per execution, and nothing is dropped either way. The
 * filters work on the loaded executions and each is a field the record carries.
 */
export function RedTeamResults({
  executions,
  truncated,
  status,
  errorMessage,
  onRetry,
  filters,
  onFiltersChange,
  runs,
  onOpen,
  selectedId,
}: {
  executions: ExecutionRecord[];
  truncated: boolean;
  status: AsyncStatus;
  errorMessage: string | null;
  onRetry: () => void;
  filters: ResultFilters;
  onFiltersChange: (next: ResultFilters) => void;
  runs: RunRecord[];
  onOpen: (executionId: string) => void;
  selectedId: string | null;
}) {
  const [grouped, setGrouped] = useState(true);
  const [expanded, setExpanded] = useState<Set<string>>(() => new Set());
  const filtered = Boolean(
    filters.category || filters.outcome || filters.runId,
  );
  const shown = executions.filter(
    (e) =>
      (!filters.category || e.category === filters.category) &&
      (!filters.outcome || e.outcome === filters.outcome) &&
      (!filters.runId || e.run_id === filters.runId),
  );
  const rows = buildRows(shown, grouped, !filters.outcome && !filters.runId);

  function toggle(key: string) {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (!next.delete(key)) next.add(key);
      return next;
    });
  }

  return (
    <div>
      <div
        role="search"
        aria-label="Filter executions"
        className="grid grid-cols-2 items-end gap-3 sm:flex sm:flex-wrap"
      >
        <label className="flex min-w-0 flex-col gap-1 text-base sm:text-sm">
          <span className="text-text-tertiary">Category</span>
          <select
            className={CONTROL}
            value={filters.category}
            onChange={(e) =>
              onFiltersChange({
                ...filters,
                category: e.target.value as Category | "",
              })
            }
          >
            <option value="">All categories</option>
            {CATEGORY_ORDER.map((c) => (
              <option key={c} value={c}>
                {CATEGORY_LABEL[c]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex min-w-0 flex-col gap-1 text-base sm:text-sm">
          <span className="text-text-tertiary">Outcome</span>
          <select
            className={CONTROL}
            value={filters.outcome}
            onChange={(e) =>
              onFiltersChange({
                ...filters,
                outcome: e.target.value as Outcome | "",
              })
            }
          >
            <option value="">All outcomes</option>
            {OUTCOMES.map((o) => (
              <option key={o} value={o}>
                {OUTCOME_LABEL[o]}
              </option>
            ))}
          </select>
        </label>
        <label className="flex min-w-0 flex-col gap-1 text-base sm:text-sm">
          <span className="text-text-tertiary">Run</span>
          <select
            className={CONTROL}
            value={filters.runId}
            onChange={(e) =>
              onFiltersChange({ ...filters, runId: e.target.value })
            }
          >
            <option value="">All runs</option>
            {runs.map((r) => (
              <option key={r.run_id} value={r.run_id}>
                {shortId(r.run_id)}, {formatUtcSeconds(r.created_at)} UTC,{" "}
                {r.status}
              </option>
            ))}
          </select>
        </label>
        <button
          type="button"
          aria-pressed={!grouped}
          onClick={() => setGrouped((g) => !g)}
          className={`min-h-11 rounded-lg border px-3 text-base sm:text-sm ${grouped ? "border-border-strong text-text-primary hover:bg-surface" : "border-line-active bg-surface-high text-text-primary"}`}
        >
          {grouped ? "Show every execution" : "Group repeated results"}
        </button>
        {filtered ? (
          <button
            type="button"
            onClick={() =>
              onFiltersChange({ category: "", outcome: "", runId: "" })
            }
            className="border-border-strong text-text-primary hover:bg-surface min-h-11 rounded-lg border px-3 text-base sm:text-sm"
          >
            Clear filters
          </button>
        ) : null}
      </div>

      <div className="mt-5">
        <AsyncState
          status={status}
          errorMessage={errorMessage}
          onRetry={onRetry}
          loadingLabel="Loading stored executions…"
        >
          {truncated ? (
            <p role="status" className="text-warning mb-3 text-base sm:text-sm">
              Only the newest {executions.length} stored executions were loaded.
              Older ones exist and are not shown.
            </p>
          ) : null}
          <p
            role="status"
            className="text-text-secondary mb-3 text-base sm:text-sm"
          >
            {shown.length} {shown.length === 1 ? "execution" : "executions"}
            {grouped && rows.length !== shown.length
              ? ` in ${rows.length} rows, because repeated identical results are grouped`
              : ""}
            .
          </p>
          {rows.length === 0 ? (
            <div className="border-border-strong rounded-xl border border-dashed px-6 py-12 text-center">
              <p className="text-text-primary text-base">
                {filtered
                  ? "No stored execution matches these filters."
                  : "No execution has been stored yet."}
              </p>
              <p className="text-text-secondary mt-1 text-base">
                {filtered
                  ? "Clear a filter to see more."
                  : "Run a scenario above and its result appears here."}
              </p>
            </div>
          ) : (
            <>
              <table className="hidden w-full table-fixed text-left lg:table">
                <caption className="sr-only">
                  Stored Red Team executions, newest first. Repeated identical
                  results are grouped unless every execution is shown.
                </caption>
                <colgroup>
                  <col className="w-[10.5rem]" />
                  <col />
                  <col className="w-[15rem]" />
                  <col className="w-[17rem]" />
                  <col className="w-[13rem]" />
                </colgroup>
                <thead>
                  <tr>
                    {[
                      "Time, UTC",
                      "Scenario",
                      "Expected",
                      "Observed",
                      "Against expectation",
                    ].map((head) => (
                      <th
                        key={head}
                        scope="col"
                        className="text-text-tertiary bg-background border-border-strong sticky top-[calc(var(--nav-h)+2.75rem)] z-10 border-b px-3 py-3 text-sm font-normal first:pl-5"
                      >
                        {head}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row) => {
                    const open = expanded.has(row.key);
                    return (
                      <Fragment key={row.key}>
                        <tr
                          aria-current={
                            row.executions.some(
                              (e) => e.execution_id === selectedId,
                            )
                              ? "true"
                              : undefined
                          }
                          data-rail="true"
                          style={
                            {
                              "--tone": rowTone(row.last),
                            } as React.CSSProperties
                          }
                          className="trace-row border-border border-b"
                        >
                          <td className="text-text-tertiary tabular-metric py-3 pr-3 pl-5 align-top text-xs whitespace-nowrap">
                            <When row={row} />
                          </td>
                          <td className="px-3 py-1.5 align-top">
                            <ScenarioCell
                              row={row}
                              expanded={open}
                              onToggle={() => toggle(row.key)}
                              onOpen={onOpen}
                            />
                          </td>
                          <td className="text-text-secondary px-3 py-3 align-top text-sm">
                            {expectedLabel(row.last.expected)}
                          </td>
                          <td className="px-3 py-3 align-top">
                            <Observed row={row} />
                          </td>
                          <td className="px-3 py-3 align-top">
                            <ExpectationChip e={row.last} />
                          </td>
                        </tr>
                        {open ? (
                          <tr>
                            <td colSpan={5} className="p-0">
                              <Expanded row={row} onOpen={onOpen} />
                            </td>
                          </tr>
                        ) : null}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>

              <ul className="border-border border-t lg:hidden">
                {rows.map((row) => {
                  const open = expanded.has(row.key);
                  return (
                    <li
                      key={row.key}
                      aria-current={
                        row.executions.some(
                          (e) => e.execution_id === selectedId,
                        )
                          ? "true"
                          : undefined
                      }
                      data-rail="true"
                      style={
                        { "--tone": rowTone(row.last) } as React.CSSProperties
                      }
                      className="trace-row border-border border-b"
                    >
                      <div className="px-3 py-2">
                        <ScenarioCell
                          row={row}
                          expanded={open}
                          onToggle={() => toggle(row.key)}
                          onOpen={onOpen}
                        />
                        <p className="text-text-tertiary text-base tabular-nums">
                          <When row={row} /> UTC
                        </p>
                        <div className="mt-1.5 flex flex-wrap items-center gap-2 pb-1">
                          <Observed row={row} />
                          <ExpectationChip e={row.last} />
                        </div>
                      </div>
                      {open ? <Expanded row={row} onOpen={onOpen} /> : null}
                    </li>
                  );
                })}
              </ul>
            </>
          )}
        </AsyncState>
      </div>
    </div>
  );
}
