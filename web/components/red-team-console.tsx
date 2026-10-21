"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { type AsyncStatus } from "@/components/async-state";
import { SectionRail } from "@/components/incidents/section-rail";
import { RedTeamAttention } from "@/components/red-team-attention";
import { RedTeamEvidence } from "@/components/red-team-evidence";
import { RedTeamExplorer } from "@/components/red-team-explorer";
import {
  RedTeamResults,
  type ResultFilters,
} from "@/components/red-team-results";
import { RedTeamExecute } from "@/components/red-team-execute";
import { RedTeamScenario } from "@/components/red-team-scenario";
import type { Summary } from "@/lib/incidents";
import { fetchIncidents } from "@/lib/incidents-api";
import { useIsDesktop } from "@/lib/use-is-desktop";
import { usePrefersReducedMotion } from "@/lib/use-prefers-reduced-motion";
import {
  CATEGORY_ORDER,
  MODES,
  OUTCOMES,
  SEVERITIES,
  STATUSES,
  attentionItems,
  byScenario,
  countExecutions,
  filterScenarios,
  groupByLayer,
  summarizeLatest,
  type Category,
  type ExecutionRecord,
  type ExplorerFilters,
  type Mode,
  type Outcome,
  type RunDetail,
  type RunRecord,
  type ScenarioList,
  type ScenarioStatus,
  type Severity,
} from "@/lib/red-team";
import {
  RedTeamApiError,
  fetchAllExecutions,
  fetchRun,
  fetchRuns,
  fetchScenarios,
  startRun,
} from "@/lib/red-team-api";

const POLL_MS = 1500;

const SECTIONS = [
  { id: "attention", label: "Attention" },
  { id: "defenses", label: "Scenarios" },
  { id: "executions", label: "History" },
  { id: "execute", label: "Run scenarios" },
];

function oneOf<T extends string>(value: string | null, allowed: readonly T[]) {
  return allowed.find((a) => a === value) ?? "";
}

function message(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

/**
 * The Red Team console. Every figure on it comes from the scenario registry and the stored
 * executions through /ops/redteam, read once and derived from. Reading it starts nothing: the
 * page reads in this order, what needs attention, the scenarios, then the execution history,
 * and the one thing that can start a run is the execution workflow at the end, behind a
 * confirmation. A confirmed run only creates stored rows, and the console re-reads them after.
 */
export function RedTeamConsole() {
  const searchParams = useSearchParams();
  const desktop = useIsDesktop();
  const reduced = usePrefersReducedMotion();

  const [overview, setOverview] = useState<ScenarioList | null>(null);
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [overviewStatus, setOverviewStatus] = useState<AsyncStatus>("loading");
  const [overviewError, setOverviewError] = useState<string | null>(null);

  const [executions, setExecutions] = useState<ExecutionRecord[]>([]);
  const [truncated, setTruncated] = useState(false);
  const [execStatus, setExecStatus] = useState<AsyncStatus>("loading");
  const [execError, setExecError] = useState<string | null>(null);
  const [sessions, setSessions] = useState<Summary[] | null>(null);

  const [filters, setFilters] = useState<ResultFilters>(() => ({
    category: oneOf<Category>(searchParams.get("category"), CATEGORY_ORDER),
    outcome: oneOf<Outcome>(searchParams.get("outcome"), OUTCOMES),
    runId: searchParams.get("run") ?? "",
  }));
  const [explorerFilters, setExplorerFilters] = useState<ExplorerFilters>(
    () => ({
      status: oneOf<ScenarioStatus>(searchParams.get("status"), STATUSES),
      query: searchParams.get("q") ?? "",
      result: oneOf<Outcome | "not_run">(searchParams.get("result"), [
        ...OUTCOMES,
        "not_run",
      ]),
      severity: oneOf<Severity>(searchParams.get("severity"), SEVERITIES),
      mode: oneOf<Mode>(searchParams.get("mode"), MODES),
      category: oneOf<Category>(
        searchParams.get("scenario_category"),
        CATEGORY_ORDER,
      ),
    }),
  );
  const [chosen, setChosen] = useState<string | null>(
    searchParams.get("scenario"),
  );
  const [openExecution, setOpenExecution] = useState<string | null>(
    searchParams.get("execution"),
  );

  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [activeRun, setActiveRun] = useState<RunDetail | null>(null);
  const [starting, setStarting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [executeOpen, setExecuteOpen] = useState(false);
  const [historyOpen, setHistoryOpen] = useState(() =>
    Boolean(
      searchParams.get("run") ||
      searchParams.get("outcome") ||
      searchParams.get("category"),
    ),
  );
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [refreshToken, setRefreshToken] = useState(0);

  // The registry comes first and does not depend on the result store, so a store outage
  // cannot hide it. A run left running by an earlier page load is followed.
  useEffect(() => {
    let cancelled = false;
    fetchScenarios()
      .then((list) => {
        if (cancelled) return;
        setOverview(list);
        setOverviewStatus("ready");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setOverviewError(message(err, "The Red Team API is unreachable."));
        setOverviewStatus("error");
      });
    fetchRuns()
      .then((history) => {
        if (cancelled) return;
        setRuns(history);
        const running = history.find((r) => r.status === "running");
        if (running) setActiveRunId((id) => id ?? running.run_id);
      })
      .catch(() => {
        // The executions section reports the same outage with its own message.
      });
    fetchAllExecutions()
      .then((loaded) => {
        if (cancelled) return;
        setExecutions(loaded.executions);
        setTruncated(loaded.truncated);
        setExecStatus("ready");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setExecError(message(err, "The Red Team API is unreachable."));
        setExecStatus("error");
      });
    // Stored investigations only decide whether "Investigate this" offers an existing one.
    fetchIncidents(0, "", 50)
      .then((page) => {
        if (!cancelled) setSessions(page.investigations);
      })
      .catch(() => {
        if (!cancelled) setSessions(null);
      });
    return () => {
      cancelled = true;
    };
  }, [refreshToken]);

  // Plain REST reads of one bounded run while it is active. This is not a live feed: each
  // tick reads the stored rows, and it stops when the run ends.
  useEffect(() => {
    if (activeRunId === null) return;
    let cancelled = false;
    async function tick(id: string) {
      try {
        const detail = await fetchRun(id);
        if (cancelled) return;
        setActiveRun(detail);
        setNotice(null);
        if (detail.run.status !== "running") {
          setActiveRunId(null);
          setRefreshToken((n) => n + 1);
        }
      } catch (err: unknown) {
        if (!cancelled) {
          setNotice(
            `Run progress could not be read. ${message(err, "")} Retrying.`,
          );
        }
      }
    }
    void tick(activeRunId);
    const timer = setInterval(() => void tick(activeRunId), POLL_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
    };
  }, [activeRunId]);

  // Keep the URL in step so a filtered view, a scenario or an open execution can be shared.
  useEffect(() => {
    const params = new URLSearchParams();
    if (filters.category) params.set("category", filters.category);
    if (filters.outcome) params.set("outcome", filters.outcome);
    if (filters.runId) params.set("run", filters.runId);
    if (explorerFilters.status) params.set("status", explorerFilters.status);
    if (explorerFilters.query.trim()) params.set("q", explorerFilters.query);
    if (explorerFilters.result) params.set("result", explorerFilters.result);
    if (explorerFilters.severity)
      params.set("severity", explorerFilters.severity);
    if (explorerFilters.mode) params.set("mode", explorerFilters.mode);
    if (explorerFilters.category)
      params.set("scenario_category", explorerFilters.category);
    if (chosen) params.set("scenario", chosen);
    if (openExecution) params.set("execution", openExecution);
    const qs = params.toString();
    window.history.replaceState(null, "", qs ? `/red-team?${qs}` : "/red-team");
  }, [filters, explorerFilters, chosen, openExecution]);

  async function start(ids: string[] | null, judgeAssisted: boolean) {
    setStarting(true);
    setNotice(null);
    try {
      const detail = await startRun(ids, judgeAssisted);
      setActiveRun(detail);
      setActiveRunId(detail.run.run_id);
      setSelected(new Set());
      setRefreshToken((n) => n + 1);
    } catch (err: unknown) {
      setNotice(message(err, "The run could not be started."));
      if (err instanceof RedTeamApiError && err.activeRunId) {
        setActiveRunId(err.activeRunId);
      }
    } finally {
      setStarting(false);
    }
  }

  const scenarios = useMemo(() => overview?.scenarios ?? [], [overview]);
  const summary = useMemo(() => summarizeLatest(scenarios), [scenarios]);
  const histories = useMemo(() => byScenario(executions), [executions]);
  const items = useMemo(
    () => attentionItems(scenarios, histories),
    [scenarios, histories],
  );
  const executionCounts = useMemo(
    () => (execStatus === "ready" ? countExecutions(executions) : null),
    [executions, execStatus],
  );
  const executors = useMemo(
    () => Object.fromEntries(scenarios.map((s) => [s.id, s.executor])),
    [scenarios],
  );
  const visibleScenarios = useMemo(
    () => filterScenarios(scenarios, explorerFilters),
    [scenarios, explorerFilters],
  );
  const firstScenario =
    groupByLayer(visibleScenarios)[0]?.scenarios[0]?.id ?? null;
  // A wide screen opens the most important scenario the filters leave visible, so the detail
  // is never an empty pane and never a scenario the list has hidden.
  const visibleIds = new Set(visibleScenarios.map((s) => s.id));
  const defaultSelected =
    items.find((i) => visibleIds.has(i.scenario.id))?.scenario.id ??
    firstScenario;
  const selectedId = chosen ?? (desktop ? defaultSelected : null);
  const busy = starting || activeRunId !== null;
  const persistence = overview?.persistence_available ?? false;

  function openExecute(preselect?: string) {
    if (preselect) {
      const s = scenarios.find((x) => x.id === preselect);
      if (s?.mode === "deterministic") {
        setSelected((prev) => new Set(prev).add(preselect));
      }
    }
    setExecuteOpen(true);
    requestAnimationFrame(() =>
      document.getElementById("execute")?.scrollIntoView({
        behavior: reduced ? "auto" : "smooth",
        block: "start",
      }),
    );
  }

  function focusScenario(id: string) {
    setChosen(id);
    requestAnimationFrame(() => {
      const row = document.querySelector(`[data-scenario="${CSS.escape(id)}"]`);
      const target = desktop ? document.getElementById("defenses") : row;
      target?.scrollIntoView({
        behavior: reduced ? "auto" : "smooth",
        block: "start",
      });
    });
  }

  return (
    <div className="ctx ctx-forensic mobile-readable flex-1">
      <SectionRail sections={SECTIONS} />
      <div className="mx-auto w-full max-w-7xl px-4 sm:px-8">
        <header className="flex flex-col gap-6 pt-12 pb-8 sm:pt-16 lg:flex-row lg:items-end lg:justify-between">
          <div className="max-w-3xl">
            <p className="eyebrow">
              Do the defenses hold against the attacks written for them?
            </p>
            <h1 className="text-text-primary mt-3 text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
              Red Team
            </h1>
            <p className="text-text-secondary mt-4 text-lg leading-relaxed text-pretty">
              Each scenario is a controlled attack aimed at one defense. A
              recorded execution shows whether that defense acted, which layer
              acted and what evidence it left. The results describe these
              written scenarios. They do not estimate how often a real attacker
              would get through. Reading this page never runs anything.
            </p>
          </div>
          <button
            type="button"
            onClick={() => openExecute()}
            className="text-accent hover:text-text-primary inline-flex min-h-11 shrink-0 items-center text-base underline underline-offset-4 sm:text-sm"
          >
            Run scenarios
          </button>
        </header>

        <section
          id="attention"
          aria-labelledby="attention-heading"
          className="border-border border-t py-10"
        >
          <h2 id="attention-heading" className="eyebrow">
            What needs attention
          </h2>
          <div className="mt-4">
            {overviewStatus === "loading" ? (
              <div
                role="status"
                aria-label="Loading the scenario registry"
                className="space-y-3"
              >
                <div className="bg-surface h-7 w-2/3 rounded motion-safe:animate-pulse" />
                <div className="bg-surface h-40 w-full rounded motion-safe:animate-pulse" />
                <span className="sr-only">Loading the scenario registry…</span>
              </div>
            ) : overviewStatus === "error" ? (
              <div
                role="alert"
                className="border-failure/40 bg-failure/5 flex flex-wrap items-center gap-4 rounded-lg border p-5"
              >
                <p className="text-text-primary text-base">{overviewError}</p>
                <button
                  type="button"
                  onClick={() => {
                    setOverviewStatus("loading");
                    setRefreshToken((n) => n + 1);
                  }}
                  className="border-border-strong text-text-primary hover:bg-surface min-h-11 rounded-lg border px-4 text-base font-medium"
                >
                  Retry
                </button>
              </div>
            ) : (
              <RedTeamAttention
                summary={summary}
                items={items}
                executionCounts={executionCounts}
                persistence={persistence}
                sessions={sessions}
                onOpenScenario={focusScenario}
                onOpenEvidence={setOpenExecution}
                onStarted={() => setRefreshToken((n) => n + 1)}
              />
            )}
          </div>
        </section>

        {overviewStatus === "ready" ? (
          <section
            id="defenses"
            aria-labelledby="defenses-heading"
            className="border-border border-t py-12"
          >
            <h2 id="defenses-heading" className="eyebrow">
              Scenarios, in the order a request meets their defense
            </h2>
            <p className="text-text-secondary mt-3 max-w-3xl text-base leading-relaxed">
              {scenarios.length} versioned scenarios. The expectation is stored
              with each scenario, and the result comes only from running it.
              Select one to read what it expects and what was recorded.
            </p>
            <div className="mt-6">
              <RedTeamExplorer
                scenarios={scenarios}
                histories={histories}
                filters={explorerFilters}
                onFiltersChange={setExplorerFilters}
                selectedId={selectedId}
                onSelect={(id) =>
                  setChosen((cur) => (cur === id && !desktop ? null : id))
                }
                renderDetail={(s) => (
                  <RedTeamScenario
                    scenario={s}
                    history={histories.get(s.id) ?? []}
                    sessions={sessions}
                    onSetupRun={openExecute}
                    onOpenEvidence={setOpenExecution}
                    onStarted={() => setRefreshToken((n) => n + 1)}
                  />
                )}
              />
            </div>
          </section>
        ) : null}

        <section
          id="executions"
          aria-labelledby="executions-heading"
          className="border-border border-t py-10"
        >
          <h2 id="executions-heading" className="eyebrow">
            Execution history
          </h2>
          <button
            type="button"
            aria-expanded={historyOpen}
            aria-controls="history-body"
            onClick={() => setHistoryOpen((o) => !o)}
            className="border-border-strong hover:bg-surface mt-3 flex min-h-12 w-full items-center justify-between gap-4 rounded-xl border px-4 py-3 text-left sm:px-5"
          >
            <span>
              <span className="text-text-primary block text-base font-medium">
                {execStatus === "ready"
                  ? `${executions.length}${truncated ? "+" : ""} recorded ${executions.length === 1 ? "execution" : "executions"}`
                  : execStatus === "error"
                    ? "The execution history could not be read"
                    : "Loading the execution history"}
              </span>
              <span className="text-text-secondary block text-base sm:text-sm">
                Newest first. Repeated identical results are one row with a
                count, and a row that follows a different result says what
                changed.
              </span>
            </span>
            <span aria-hidden="true" className="text-text-tertiary">
              {historyOpen ? "Hide" : "Show"}
            </span>
          </button>
          {historyOpen ? (
            <div id="history-body" className="mt-4">
              <RedTeamResults
                executions={executions}
                truncated={truncated}
                status={execStatus}
                errorMessage={execError}
                onRetry={() => {
                  setExecStatus("loading");
                  setRefreshToken((n) => n + 1);
                }}
                filters={filters}
                onFiltersChange={setFilters}
                runs={runs}
                onOpen={setOpenExecution}
                selectedId={openExecution}
              />
            </div>
          ) : null}
        </section>

        {overviewStatus === "ready" ? (
          <section
            id="execute"
            aria-labelledby="execute-heading"
            className="border-border scroll-mt-32 border-t py-10 pb-20"
          >
            <h2 id="execute-heading" className="eyebrow">
              Execution workflow
            </h2>
            <div className="mt-3">
              <RedTeamExecute
                scenarios={scenarios}
                selected={selected}
                onSelectedChange={setSelected}
                open={executeOpen || busy}
                onOpenChange={setExecuteOpen}
                busy={busy}
                persistenceAvailable={persistence}
                activeRun={activeRun}
                startError={notice}
                onStart={(ids, judge) => void start(ids, judge)}
              />
            </div>
          </section>
        ) : null}
      </div>

      {openExecution ? (
        <RedTeamEvidence
          executionId={openExecution}
          executors={executors}
          sessions={sessions}
          onStarted={() => setRefreshToken((n) => n + 1)}
          onClose={() => setOpenExecution(null)}
        />
      ) : null}
    </div>
  );
}
