"use client";

import {
  ModeBadge,
  RedTeamOutcomeBadge,
  SeverityBadge,
  ExpectationChip,
} from "@/components/red-team-badges";
import {
  CATEGORY_LABEL,
  CATEGORY_ORDER,
  OUTCOMES,
  OUTCOME_LABEL,
  STATUSES,
  STATUS_LABEL,
  STAGE_LABEL,
  filterScenarios,
  groupByLayer,
  hasExplorerFilters,
  historySummary,
  isSafetyBoundSkip,
  layerLabel,
  NO_EXPLORER_FILTERS,
  resolveDetail,
  statusCounts,
  streaks,
  type Category,
  type ExecutionRecord,
  type ExplorerFilters,
  type Mode,
  type Outcome,
  type ScenarioView,
  type Severity,
} from "@/lib/red-team";
import { useIsDesktop } from "@/lib/use-is-desktop";

const SELECT =
  "border-border-strong bg-background-elevated text-text-primary hover:border-line-active focus-visible:border-accent min-h-11 w-full min-w-0 rounded-lg border px-3 text-base sm:text-sm";

const CHIP =
  "min-h-11 rounded-lg border px-4 text-base sm:text-sm transition-colors";

const DOT: Record<Outcome, string> = {
  caught: "bg-positive",
  missed: "bg-failure",
  evaluator_unavailable: "border border-dashed border-warning",
  execution_failed: "border border-dashed border-failure",
  inconclusive: "border border-dashed border-text-tertiary",
};

export function rowTone(s: ScenarioView): string {
  const last = s.last_execution;
  if (last === null || last.outcome === null) return "var(--text-tertiary)";
  if (last.outcome === "missed") return "var(--failure)";
  if (last.expectation === "not_met") return "var(--warning)";
  if (last.outcome === "caught") return "var(--positive)";
  return "var(--warning)";
}

function Dots({ executions }: { executions: ExecutionRecord[] }) {
  const recent = executions.slice(-12);
  return (
    <span aria-hidden="true" className="flex items-center gap-1">
      {executions.length > recent.length ? (
        <span className="text-text-tertiary text-xs">…</span>
      ) : null}
      {recent.map((e) => (
        <span
          key={e.execution_id}
          className={`h-2.5 w-2.5 rounded-sm ${e.outcome ? DOT[e.outcome] : "border border-dashed border-text-tertiary"}`}
        />
      ))}
    </span>
  );
}

function Row({
  scenario: s,
  history,
  selected,
  onSelect,
  children,
}: {
  scenario: ScenarioView;
  history: ExecutionRecord[];
  selected: boolean;
  onSelect: () => void;
  children: React.ReactNode;
}) {
  const last = s.last_execution;
  return (
    <li
      data-scenario={s.id}
      className="border-border border-b"
      style={{ ["--tone" as string]: rowTone(s) }}
    >
      <div
        className="row-reveal relative flex items-stretch"
        data-active={selected ? "true" : undefined}
      >
        <button
          type="button"
          aria-expanded={selected}
          onClick={onSelect}
          className="flex min-h-11 min-w-0 flex-1 flex-col gap-1.5 px-3 py-2.5 text-left lg:flex-row lg:items-center lg:justify-between lg:gap-6 lg:py-3"
        >
          <span className="min-w-0">
            <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="text-text-tertiary font-mono text-base sm:text-sm">
                {s.id}, version {s.version}
              </span>
              <SeverityBadge severity={s.severity} />
              {s.mode === "judge_assisted" ? (
                <ModeBadge mode={s.mode} explain={false} />
              ) : null}
            </span>
            <span className="text-text-primary mt-0.5 block text-base leading-snug font-medium">
              {s.title}
            </span>
          </span>
          <span className="flex min-w-0 flex-col gap-1 lg:items-end">
            {last === null ? (
              <span className="text-text-tertiary border-border-strong w-fit rounded-md border border-dashed px-2 py-0.5 text-xs">
                Not run
              </span>
            ) : (
              <span className="flex flex-wrap items-center gap-2">
                <RedTeamOutcomeBadge
                  outcome={last.outcome}
                  state={last.state}
                  safetyBound={isSafetyBoundSkip(last)}
                />
                {last.expectation === "not_met" ? (
                  <ExpectationChip e={last} />
                ) : null}
              </span>
            )}
            <span className="text-text-tertiary flex items-center gap-2 text-base sm:text-sm">
              <Dots executions={history} />
              {historySummary(streaks(history))}
            </span>
          </span>
        </button>
      </div>
      {children}
    </li>
  );
}

/** The scenarios as lanes along a request's path, with the four things an operator filters by
 * on top: a status and a search. Severity, mode, category and latest result stay available
 * behind one disclosure, so they never compete with the list. Summary first: a row shows the
 * title, severity, the latest result and a one-line history. The detail answers selection
 * beside the list on a wide screen and under the row on a narrow one. */
export function RedTeamExplorer({
  scenarios,
  histories,
  filters,
  onFiltersChange,
  selectedId,
  onSelect,
  renderDetail,
}: {
  scenarios: ScenarioView[];
  histories: Map<string, ExecutionRecord[]>;
  filters: ExplorerFilters;
  onFiltersChange: (next: ExplorerFilters) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
  renderDetail: (s: ScenarioView) => React.ReactNode;
}) {
  const desktop = useIsDesktop();
  const visible = filterScenarios(scenarios, filters);
  const lanes = groupByLayer(visible);
  const detail = resolveDetail(scenarios, visible, selectedId);
  const filtered = hasExplorerFilters(filters);
  const counts = statusCounts(scenarios, filters);
  const moreOpen = Boolean(
    filters.severity || filters.mode || filters.category || filters.result,
  );

  return (
    <div>
      <div role="search" aria-label="Filter scenarios" className="space-y-3">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
          <div
            role="group"
            aria-label="Filter by status"
            className="flex flex-wrap items-center gap-2"
          >
            {(["", ...STATUSES] as const).map((value) => {
              const on = filters.status === value;
              return (
                <button
                  key={value || "all"}
                  type="button"
                  aria-pressed={on}
                  onClick={() => onFiltersChange({ ...filters, status: value })}
                  className={`${CHIP} ${on ? "border-line-active bg-surface-high text-text-primary" : "border-border-strong text-text-secondary hover:text-text-primary"}`}
                >
                  {value === "" ? "All" : STATUS_LABEL[value]}
                  <span className="text-text-tertiary tabular-metric ml-2">
                    {counts[value === "" ? "all" : value]}
                  </span>
                </button>
              );
            })}
          </div>
          <label className="flex min-w-0 grow items-center sm:max-w-xs">
            <span className="sr-only">Search scenarios</span>
            <input
              type="search"
              value={filters.query}
              onChange={(e) =>
                onFiltersChange({ ...filters, query: e.target.value })
              }
              name="scenario-search"
              placeholder="Try DI-001, Prompt Guard or missed…"
              autoComplete="off"
              spellCheck={false}
              className={`${SELECT} placeholder:text-text-tertiary`}
            />
          </label>
        </div>
        <details className="group" open={moreOpen || undefined}>
          <summary className="text-accent hover:text-text-primary inline-flex min-h-11 cursor-pointer items-center text-base underline-offset-4 group-open:underline sm:text-sm">
            More filters
          </summary>
          <div className="mt-2 grid grid-cols-2 gap-3 lg:grid-cols-4">
            <label className="flex min-w-0 flex-col gap-1 text-base sm:text-sm">
              <span className="text-text-tertiary">Latest result</span>
              <select
                className={SELECT}
                value={filters.result}
                onChange={(e) =>
                  onFiltersChange({
                    ...filters,
                    result: e.target.value as ExplorerFilters["result"],
                  })
                }
              >
                <option value="">All results</option>
                {OUTCOMES.map((o) => (
                  <option key={o} value={o}>
                    {OUTCOME_LABEL[o]}
                  </option>
                ))}
                <option value="not_run">Not run</option>
              </select>
            </label>
            <label className="flex min-w-0 flex-col gap-1 text-base sm:text-sm">
              <span className="text-text-tertiary">Severity</span>
              <select
                className={SELECT}
                value={filters.severity}
                onChange={(e) =>
                  onFiltersChange({
                    ...filters,
                    severity: e.target.value as Severity | "",
                  })
                }
              >
                <option value="">All severities</option>
                {(["critical", "high", "medium", "low"] as const).map((v) => (
                  <option key={v} value={v}>
                    {v[0].toUpperCase() + v.slice(1)}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex min-w-0 flex-col gap-1 text-base sm:text-sm">
              <span className="text-text-tertiary">Mode</span>
              <select
                className={SELECT}
                value={filters.mode}
                onChange={(e) =>
                  onFiltersChange({
                    ...filters,
                    mode: e.target.value as Mode | "",
                  })
                }
              >
                <option value="">All modes</option>
                <option value="deterministic">Deterministic</option>
                <option value="judge_assisted">Judge-assisted</option>
              </select>
            </label>
            <label className="flex min-w-0 flex-col gap-1 text-base sm:text-sm">
              <span className="text-text-tertiary">Category</span>
              <select
                className={SELECT}
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
          </div>
        </details>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4">
        <p role="status" className="text-text-secondary text-base sm:text-sm">
          Showing {visible.length} of {scenarios.length} scenarios.
        </p>
        {filtered ? (
          <button
            type="button"
            onClick={() => onFiltersChange(NO_EXPLORER_FILTERS)}
            className="text-accent hover:text-text-primary min-h-11 text-base underline underline-offset-4 sm:text-sm"
          >
            Clear filters
          </button>
        ) : null}
      </div>

      <div className="mt-2 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)] lg:items-start">
        <div className="min-w-0">
          {lanes.length === 0 ? (
            <div className="border-border-strong rounded-xl border border-dashed px-6 py-12 text-center">
              <p className="text-text-primary text-base">
                No scenario matches these filters.
              </p>
            </div>
          ) : (
            lanes.map((lane) => (
              <section
                key={lane.layer}
                aria-labelledby={`lane-${lane.layer}`}
                className="mb-6 last:mb-0"
              >
                <h3
                  id={`lane-${lane.layer}`}
                  className="flex flex-wrap items-baseline gap-x-3 gap-y-1"
                >
                  <span className="text-text-primary text-lg font-semibold">
                    {layerLabel(lane.layer)}
                  </span>
                  {lane.stage ? (
                    <span className="text-text-tertiary text-base sm:text-sm">
                      {STAGE_LABEL[lane.stage]}
                    </span>
                  ) : null}
                </h3>
                <ul className="border-border mt-2 border-t">
                  {lane.scenarios.map((s) => {
                    const isSelected = s.id === selectedId;
                    return (
                      <Row
                        key={s.id}
                        scenario={s}
                        history={histories.get(s.id) ?? []}
                        selected={isSelected}
                        onSelect={() => onSelect(s.id)}
                      >
                        {isSelected && !desktop ? (
                          <div className="swap-in border-border bg-background-elevated/40 border-t px-3 py-4">
                            {renderDetail(s)}
                          </div>
                        ) : null}
                      </Row>
                    );
                  })}
                </ul>
              </section>
            ))
          )}
        </div>
        {desktop ? (
          <div className="lg:sticky lg:top-[calc(var(--nav-h)+4.25rem)] lg:max-h-[calc(100vh-var(--nav-h)-5.5rem)] lg:overflow-y-auto">
            {detail.kind === "open" ? (
              <div
                key={detail.scenario.id}
                style={{ ["--tone" as string]: rowTone(detail.scenario) }}
                className="instrument bg-background-elevated/50 rounded-xl p-5"
              >
                {renderDetail(detail.scenario)}
              </div>
            ) : detail.kind === "hidden" ? (
              <div
                role="status"
                data-detail-state="hidden"
                className="border-border-strong text-text-secondary rounded-xl border border-dashed p-6 text-base"
              >
                <p className="text-text-primary">
                  {detail.id} is hidden by the current filters.
                </p>
                <p className="mt-2">
                  Select a scenario in the list, or clear the filters to open{" "}
                  {detail.id} again.
                </p>
              </div>
            ) : (
              <div
                data-detail-state="none"
                className="border-border-strong text-text-secondary rounded-xl border border-dashed p-6 text-base"
              >
                Select a scenario to read what it expects, what was recorded and
                which defense acted.
              </div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
