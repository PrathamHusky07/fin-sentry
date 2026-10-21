"use client";

import {
  ExpectationChip,
  ModeBadge,
  RedTeamOutcomeBadge,
  SeverityBadge,
} from "@/components/red-team-badges";
import {
  CATEGORY_LABEL,
  CATEGORY_ORDER,
  OUTCOMES,
  OUTCOME_LABEL,
  STAGE_LABEL,
  filterScenarios,
  groupByLayer,
  hasExplorerFilters,
  historySummary,
  isSafetyBoundSkip,
  layerLabel,
  NO_EXPLORER_FILTERS,
  resolveDetail,
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

const DOT: Record<Outcome, string> = {
  caught: "bg-positive",
  missed: "bg-failure",
  evaluator_unavailable: "border border-dashed border-warning",
  execution_failed: "border border-dashed border-failure",
  inconclusive: "border border-dashed border-text-tertiary",
};

function rowTone(s: ScenarioView): string {
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
  selectMode,
  checked,
  disabledReason,
  onSelect,
  onToggle,
  children,
}: {
  scenario: ScenarioView;
  history: ExecutionRecord[];
  selected: boolean;
  selectMode: boolean;
  checked: boolean;
  disabledReason: string | null;
  onSelect: () => void;
  onToggle: () => void;
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
        {selectMode ? (
          <label className="relative flex h-auto min-h-11 w-11 shrink-0 items-center justify-center">
            <input
              type="checkbox"
              checked={checked}
              disabled={disabledReason !== null}
              onChange={onToggle}
              aria-label={
                disabledReason ? `${s.id} ${disabledReason}` : `Select ${s.id}`
              }
              className="peer absolute inset-0 h-full w-11 cursor-pointer opacity-0 disabled:cursor-not-allowed"
            />
            <span
              aria-hidden="true"
              className="border-border-strong peer-checked:border-accent peer-checked:bg-accent peer-focus-visible:outline-accent h-5 w-5 rounded border peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-disabled:opacity-40"
            />
            <svg
              viewBox="0 0 20 20"
              aria-hidden="true"
              className="text-background pointer-events-none absolute h-3.5 w-3.5 opacity-0 peer-checked:opacity-100"
              fill="none"
              stroke="currentColor"
              strokeWidth="3"
            >
              <path
                d="M4 10.5l4 4 8-9"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </label>
        ) : null}
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

/**
 * The scenarios as lanes along a request's path, with filters on the fields the registry and
 * the latest stored result carry. Summary first: a row shows the title, severity, the latest
 * result and a one-line history. The detail opens on selection, beside the list on a wide
 * screen and under the row on a narrow one.
 */
export function RedTeamExplorer({
  scenarios,
  histories,
  filters,
  onFiltersChange,
  selectedId,
  onSelect,
  selectMode,
  selected,
  onToggleSelected,
  busy,
  renderDetail,
}: {
  scenarios: ScenarioView[];
  histories: Map<string, ExecutionRecord[]>;
  filters: ExplorerFilters;
  onFiltersChange: (next: ExplorerFilters) => void;
  selectedId: string | null;
  onSelect: (id: string) => void;
  selectMode: boolean;
  selected: Set<string>;
  onToggleSelected: (id: string) => void;
  busy: boolean;
  renderDetail: (s: ScenarioView) => React.ReactNode;
}) {
  const desktop = useIsDesktop();
  const visible = filterScenarios(scenarios, filters);
  const lanes = groupByLayer(visible);
  const detail = resolveDetail(scenarios, visible, selectedId);
  const filtered = hasExplorerFilters(filters);

  return (
    <div>
      <div
        role="search"
        aria-label="Filter scenarios"
        className="grid grid-cols-2 gap-3 lg:grid-cols-5"
      >
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
        <div className="col-span-2 flex items-end lg:col-span-1">
          {filtered ? (
            <button
              type="button"
              onClick={() => onFiltersChange(NO_EXPLORER_FILTERS)}
              className="border-border-strong text-text-primary hover:bg-surface min-h-11 w-full rounded-lg border px-3 text-base sm:text-sm"
            >
              Clear filters
            </button>
          ) : null}
        </div>
      </div>
      <p
        role="status"
        className="text-text-secondary mt-3 text-base sm:text-sm"
      >
        Showing {visible.length} of {scenarios.length} scenarios.
      </p>

      <div className="mt-4 grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.15fr)] lg:items-start">
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
                    const judge = s.mode === "judge_assisted";
                    const isSelected = s.id === selectedId;
                    return (
                      <Row
                        key={s.id}
                        scenario={s}
                        history={histories.get(s.id) ?? []}
                        selected={isSelected}
                        selectMode={selectMode}
                        checked={selected.has(s.id)}
                        disabledReason={
                          judge
                            ? "runs alone and cannot be selected"
                            : busy
                              ? "cannot be selected while a run is active"
                              : null
                        }
                        onSelect={() => onSelect(s.id)}
                        onToggle={() => onToggleSelected(s.id)}
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
                className="swap-in border-border bg-background-elevated/50 rounded-xl border p-5"
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
                Select a scenario to read its latest result, its history and the
                definition it was written from.
              </div>
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}
