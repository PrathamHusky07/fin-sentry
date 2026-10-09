"use client";

import { AsyncState, type AsyncStatus } from "@/components/async-state";
import { ModeBadge, RedTeamOutcomeBadge } from "@/components/red-team-badges";
import { formatUtcSeconds, shortId } from "@/lib/format";
import type { ExecutionFilters } from "@/lib/red-team-api";
import {
  CATEGORY_LABEL,
  CATEGORY_ORDER,
  OUTCOMES,
  OUTCOME_LABEL,
  expectationLabel,
  expectedLabel,
  isSafetyBoundSkip,
  layerLabel,
  type Category,
  type ExecutionRecord,
  type Outcome,
  type RunRecord,
} from "@/lib/red-team";

const CONTROL =
  "border-border-strong bg-background-elevated text-text-primary hover:border-line-active focus-visible:border-accent min-h-11 min-w-0 rounded-lg border px-3 text-sm";

function rowTone(e: ExecutionRecord): string {
  if (e.outcome === "missed") return "var(--failure)";
  if (e.outcome === "caught") return "var(--positive)";
  return "var(--warning)";
}

function Observed({ e }: { e: ExecutionRecord }) {
  return (
    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
      <RedTeamOutcomeBadge
        outcome={e.outcome}
        state={e.state}
        safetyBound={isSafetyBoundSkip(e)}
      />
      {e.outcome === "caught" ? (
        <span className="text-text-secondary text-sm">
          {layerLabel(e.acting_layer)}
        </span>
      ) : null}
    </span>
  );
}

export function RedTeamResults({
  executions,
  status,
  errorMessage,
  onRetry,
  filters,
  onFiltersChange,
  runs,
  hasMore,
  loadingMore,
  onLoadMore,
  onOpen,
  selectedId,
}: {
  executions: ExecutionRecord[];
  status: AsyncStatus;
  errorMessage: string | null;
  onRetry: () => void;
  filters: ExecutionFilters;
  onFiltersChange: (next: ExecutionFilters) => void;
  runs: RunRecord[];
  hasMore: boolean;
  loadingMore: boolean;
  onLoadMore: () => void;
  onOpen: (executionId: string) => void;
  selectedId: string | null;
}) {
  const filtered = filters.category || filters.outcome || filters.runId;
  return (
    <section aria-labelledby="rt-results-heading" className="mt-12">
      <h2 id="rt-results-heading" className="eyebrow">
        Stored executions
      </h2>
      <p className="text-text-secondary mt-3 max-w-3xl text-base leading-relaxed">
        One row per stored execution, newest run first. Nothing is grouped by
        scenario, so a rerun is its own row. Open a row for the evidence.
      </p>

      <div role="search" className="mt-5 flex flex-wrap gap-3">
        <label className="flex min-w-0 flex-col gap-1 text-sm">
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
        <label className="flex min-w-0 flex-col gap-1 text-sm">
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
        <label className="flex min-w-0 flex-col gap-1 text-sm">
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
        {filtered ? (
          <button
            type="button"
            onClick={() =>
              onFiltersChange({ category: "", outcome: "", runId: "" })
            }
            className="border-border-strong text-text-primary hover:bg-surface min-h-11 self-end rounded-lg border px-3 text-sm"
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
          {executions.length === 0 ? (
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
                  Stored Red Team executions, newest run first. Each row opens
                  its evidence.
                </caption>
                <colgroup>
                  <col className="w-[10.5rem]" />
                  <col />
                  <col className="w-[15rem]" />
                  <col className="w-[16rem]" />
                  <col className="w-[8.5rem]" />
                  <col className="w-[12rem]" />
                </colgroup>
                <thead>
                  <tr>
                    {[
                      "Time, UTC",
                      "Scenario",
                      "Expected",
                      "Observed",
                      "Mode",
                      "Against expectation",
                    ].map((head) => (
                      <th
                        key={head}
                        scope="col"
                        className="text-text-tertiary bg-background border-border-strong sticky top-[var(--nav-h)] z-10 border-b px-3 py-3 text-sm font-normal first:pl-5"
                      >
                        {head}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {executions.map((e) => (
                    <tr
                      key={e.execution_id}
                      aria-current={
                        e.execution_id === selectedId ? "true" : undefined
                      }
                      data-rail="true"
                      style={{ "--tone": rowTone(e) } as React.CSSProperties}
                      className="trace-row border-border border-b"
                    >
                      <td className="text-text-tertiary tabular-metric py-3 pr-3 pl-5 align-top text-xs whitespace-nowrap">
                        {e.started_at
                          ? formatUtcSeconds(e.started_at)
                          : "Queued"}
                      </td>
                      <td className="px-3 py-1.5 align-top">
                        <button
                          type="button"
                          onClick={() => onOpen(e.execution_id)}
                          aria-label={`Open evidence for ${e.scenario_id}, run ${shortId(e.run_id)}`}
                          className="flex min-h-11 w-full flex-col items-start justify-center rounded-md text-left"
                        >
                          <span className="text-text-primary text-sm font-medium">
                            {e.scenario_id}, version {e.scenario_version}
                          </span>
                          <span className="text-text-tertiary text-xs">
                            {CATEGORY_LABEL[e.category]}
                          </span>
                        </button>
                      </td>
                      <td className="text-text-secondary px-3 py-3 align-top text-sm">
                        {expectedLabel(e.expected)}
                      </td>
                      <td className="px-3 py-3 align-top">
                        <Observed e={e} />
                      </td>
                      <td className="px-3 py-3 align-top">
                        <ModeBadge mode={e.mode} explain={false} />
                      </td>
                      <td className="text-text-secondary px-3 py-3 align-top text-sm">
                        {expectationLabel(e)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>

              <ul className="border-border border-t lg:hidden">
                {executions.map((e) => (
                  <li
                    key={e.execution_id}
                    aria-current={
                      e.execution_id === selectedId ? "true" : undefined
                    }
                    data-rail="true"
                    style={{ "--tone": rowTone(e) } as React.CSSProperties}
                    className="trace-row border-border border-b"
                  >
                    <button
                      type="button"
                      onClick={() => onOpen(e.execution_id)}
                      aria-label={`Open evidence for ${e.scenario_id}, run ${shortId(e.run_id)}`}
                      className="flex min-h-11 w-full flex-col gap-2 px-3 py-4 text-left"
                    >
                      <span className="text-text-primary text-base font-medium">
                        {e.scenario_id}, version {e.scenario_version}
                      </span>
                      <span className="text-text-tertiary text-sm">
                        {CATEGORY_LABEL[e.category]}
                        {e.started_at
                          ? `, ${formatUtcSeconds(e.started_at)} UTC`
                          : ""}
                      </span>
                      <span className="flex flex-wrap items-center gap-2">
                        <Observed e={e} />
                        <ModeBadge mode={e.mode} explain={false} />
                      </span>
                      <span className="text-text-secondary text-sm">
                        Expected {expectedLabel(e.expected)}.{" "}
                        {expectationLabel(e)}.
                      </span>
                    </button>
                  </li>
                ))}
              </ul>

              {hasMore ? (
                <button
                  type="button"
                  disabled={loadingMore}
                  onClick={onLoadMore}
                  className="border-border-strong text-text-primary hover:bg-surface mt-4 min-h-11 rounded-lg border px-4 text-sm font-medium disabled:opacity-50"
                >
                  {loadingMore ? "Loading…" : "Show more executions"}
                </button>
              ) : null}
            </>
          )}
        </AsyncState>
      </div>
    </section>
  );
}
