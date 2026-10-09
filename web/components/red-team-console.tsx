"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AsyncState, type AsyncStatus } from "@/components/async-state";
import { PageHeader } from "@/components/page-header";
import { RedTeamEvidence } from "@/components/red-team-evidence";
import { RedTeamRegistry } from "@/components/red-team-registry";
import { RedTeamResults } from "@/components/red-team-results";
import { RedTeamRunBar } from "@/components/red-team-run-bar";
import { RedTeamSummary } from "@/components/red-team-summary";
import {
  CATEGORY_ORDER,
  OUTCOMES,
  summarizeLatest,
  type Category,
  type ExecutionRecord,
  type Outcome,
  type RunDetail,
  type RunRecord,
  type ScenarioList,
} from "@/lib/red-team";
import {
  RedTeamApiError,
  fetchExecutions,
  fetchRun,
  fetchRuns,
  fetchScenarios,
  startRun,
  type ExecutionFilters,
} from "@/lib/red-team-api";

const POLL_MS = 1500;

function oneOf<T extends string>(value: string | null, allowed: readonly T[]) {
  return allowed.find((a) => a === value) ?? "";
}

function message(err: unknown, fallback: string): string {
  return err instanceof Error ? err.message : fallback;
}

/**
 * The Red Team operator console. Every figure on it comes from the result
 * store through /ops/redteam. Starting a run only creates stored rows. The
 * counts, the table and the evidence all re-read those rows afterwards.
 */
export function RedTeamConsole() {
  const searchParams = useSearchParams();

  const [overview, setOverview] = useState<ScenarioList | null>(null);
  const [runs, setRuns] = useState<RunRecord[]>([]);
  const [overviewStatus, setOverviewStatus] = useState<AsyncStatus>("loading");
  const [overviewError, setOverviewError] = useState<string | null>(null);

  const [filters, setFilters] = useState<ExecutionFilters>(() => ({
    category: oneOf<Category>(searchParams.get("category"), CATEGORY_ORDER),
    outcome: oneOf<Outcome>(searchParams.get("outcome"), OUTCOMES),
    runId: searchParams.get("run") ?? "",
  }));
  const [executions, setExecutions] = useState<ExecutionRecord[]>([]);
  const [nextOffset, setNextOffset] = useState<number | null>(null);
  const [execStatus, setExecStatus] = useState<AsyncStatus>("loading");
  const [execError, setExecError] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);

  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [activeRun, setActiveRun] = useState<RunDetail | null>(null);
  const [starting, setStarting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [selected, setSelected] = useState<Set<string>>(() => new Set());
  const [openExecution, setOpenExecution] = useState<string | null>(
    searchParams.get("execution"),
  );
  const [refreshToken, setRefreshToken] = useState(0);

  // The registry comes first and does not depend on the result store. Run
  // history is separate, so a store outage cannot hide the registry. A run left
  // in running state by an earlier page load is followed rather than ignored.
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
        // The executions table reports the same outage with its own message.
      });
    return () => {
      cancelled = true;
    };
  }, [refreshToken]);

  // The stored executions for the current filters, first page.
  useEffect(() => {
    let cancelled = false;
    fetchExecutions(filters, 0)
      .then((page) => {
        if (cancelled) return;
        setExecutions(page.executions);
        setNextOffset(page.next_offset);
        setExecStatus("ready");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setExecError(message(err, "The Red Team API is unreachable."));
        setExecStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [filters, refreshToken]);

  // Plain REST reads of one bounded run while it is active. This is not a
  // live feed: each tick reads the stored rows, and it stops when the run ends.
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

  // Keep the URL in step so a filtered view or an open execution can be shared.
  useEffect(() => {
    const params = new URLSearchParams();
    if (filters.category) params.set("category", filters.category);
    if (filters.outcome) params.set("outcome", filters.outcome);
    if (filters.runId) params.set("run", filters.runId);
    if (openExecution) params.set("execution", openExecution);
    const qs = params.toString();
    window.history.replaceState(null, "", qs ? `/red-team?${qs}` : "/red-team");
  }, [filters, openExecution]);

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

  function loadMore() {
    if (nextOffset === null) return;
    setLoadingMore(true);
    fetchExecutions(filters, nextOffset)
      .then((page) => {
        setExecutions((prev) => [...prev, ...page.executions]);
        setNextOffset(page.next_offset);
      })
      .catch((err: unknown) =>
        setNotice(message(err, "More executions could not be loaded.")),
      )
      .finally(() => setLoadingMore(false));
  }

  const scenarios = useMemo(() => overview?.scenarios ?? [], [overview]);
  const summary = useMemo(() => summarizeLatest(scenarios), [scenarios]);
  const busy = starting || activeRunId !== null;
  const persistence = overview?.persistence_available ?? false;

  return (
    <div className="ctx ctx-forensic flex-1">
      <div className="mx-auto w-full max-w-7xl px-4 py-12 sm:px-8 sm:py-16">
        <PageHeader eyebrow="Adversarial testing" title="Red Team">
          Fin-Sentry attacks its own defenses here. Each scenario is a stored
          attack aimed at a real rail. Every result below is a persisted
          execution, with the layer that acted and the evidence it left.
        </PageHeader>

        <div className="mt-10">
          <AsyncState
            status={overviewStatus}
            errorMessage={overviewError}
            onRetry={() => {
              setOverviewStatus("loading");
              setRefreshToken((n) => n + 1);
            }}
            loadingLabel="Loading the scenario registry"
          >
            <RedTeamSummary
              summary={summary}
              persistenceAvailable={persistence}
            />
            <RedTeamRunBar
              deterministicCount={
                scenarios.filter((s) => s.mode === "deterministic").length
              }
              selectedCount={selected.size}
              busy={busy}
              persistenceAvailable={persistence}
              activeRun={activeRun}
              startError={notice}
              onRunAll={() => void start(null, false)}
              onRunSelected={() =>
                void start(
                  scenarios.filter((s) => selected.has(s.id)).map((s) => s.id),
                  false,
                )
              }
            />
            <RedTeamRegistry
              scenarios={scenarios}
              selected={selected}
              busy={busy || !persistence}
              onToggle={(id) =>
                setSelected((prev) => {
                  const next = new Set(prev);
                  if (!next.delete(id)) next.add(id);
                  return next;
                })
              }
              onRunOne={(id, judge) => void start([id], judge)}
            />
          </AsyncState>
        </div>

        <RedTeamResults
          executions={executions}
          status={execStatus}
          errorMessage={execError}
          onRetry={() => {
            setExecStatus("loading");
            setRefreshToken((n) => n + 1);
          }}
          filters={filters}
          onFiltersChange={(next) => {
            setExecStatus("loading");
            setFilters(next);
          }}
          runs={runs}
          hasMore={nextOffset !== null}
          loadingMore={loadingMore}
          onLoadMore={loadMore}
          onOpen={setOpenExecution}
          selectedId={openExecution}
        />
      </div>

      {openExecution ? (
        <RedTeamEvidence
          executionId={openExecution}
          onClose={() => setOpenExecution(null)}
        />
      ) : null}
    </div>
  );
}
