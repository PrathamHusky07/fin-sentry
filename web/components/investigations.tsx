"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AsyncState, type AsyncStatus } from "@/components/async-state";
import {
  EMPTY_FILTERS,
  InvestigationsFilters,
  hasActiveFilters,
  type InvestigationsFilterState,
} from "@/components/investigations-filters";
import { InvestigationsTable } from "@/components/investigations-table";
import { PageHeader } from "@/components/page-header";
import { TraceDrilldown } from "@/components/trace-drilldown";
import { GATEWAY_URL } from "@/lib/config";
import type { TraceListResponse } from "@/lib/trace-api";

const PAGE_SIZE = 50;

function buildQuery(
  filters: InvestigationsFilterState,
  offset: number,
): string {
  const params = new URLSearchParams({
    limit: String(PAGE_SIZE),
    offset: String(offset),
  });
  if (filters.q) params.set("q", filters.q);
  if (filters.ticker) params.set("ticker", filters.ticker);
  if (filters.ragStatus) params.set("status", filters.ragStatus);
  if (filters.judgeState) params.set("judge_state", filters.judgeState);
  if (filters.frontierSampled)
    params.set("frontier_sampled", filters.frontierSampled);
  if (filters.disagreement) params.set("disagreement", "true");
  return params.toString();
}

/**
 * The forensic workspace. Search, filters, the flash/frontier disagreement
 * lens and server-side pagination over every persisted execution. One row
 * is one execution: nothing here is ever grouped, sampled or deduplicated.
 */
export function Investigations() {
  const searchParams = useSearchParams();

  const [filters, setFilters] = useState<InvestigationsFilterState>(() => ({
    ...EMPTY_FILTERS,
    q: searchParams.get("q") ?? "",
    ticker: searchParams.get("ticker") ?? "",
    ragStatus: searchParams.get("status") ?? "",
    judgeState: searchParams.get("judge_state") ?? "",
    frontierSampled: searchParams.get("frontier_sampled") ?? "",
    disagreement: searchParams.get("disagreement") === "true",
  }));
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<TraceListResponse | null>(null);
  const [status, setStatus] = useState<AsyncStatus>("loading");
  const [fetching, setFetching] = useState(true);
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [retryToken, setRetryToken] = useState(0);
  const [selected, setSelected] = useState<string | null>(
    searchParams.get("trace"),
  );
  const [disagreementIds, setDisagreementIds] = useState<Set<string>>(
    () => new Set(),
  );

  // The disagreement set is small and changes rarely, so it is fetched once
  // and used only to mark rows. An unavailable set just means no marks.
  useEffect(() => {
    let cancelled = false;
    fetch(`${GATEWAY_URL}/ops/traces?disagreement=true&limit=500`)
      .then((res) =>
        res.ok ? (res.json() as Promise<TraceListResponse>) : null,
      )
      .then((body) => {
        if (!cancelled && body) {
          setDisagreementIds(new Set(body.traces.map((t) => t.app_trace_id)));
        }
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  // Debounce the free-text search so every keystroke doesn't fire a request.
  // Resets pagination to page 1 on the same tick a new search term lands.
  const [debouncedQ, setDebouncedQ] = useState(filters.q);
  useEffect(() => {
    const id = setTimeout(() => {
      setDebouncedQ(filters.q);
      setOffset(0);
    }, 300);
    return () => clearTimeout(id);
  }, [filters.q]);

  // Keep the URL in step with the workspace so a filtered view or an open
  // trace can be reloaded or shared. replaceState, not pushState: typing in
  // the search box should not fill the back button with entries.
  useEffect(() => {
    const params = new URLSearchParams();
    if (filters.q) params.set("q", filters.q);
    if (filters.ticker) params.set("ticker", filters.ticker);
    if (filters.ragStatus) params.set("status", filters.ragStatus);
    if (filters.judgeState) params.set("judge_state", filters.judgeState);
    if (filters.frontierSampled)
      params.set("frontier_sampled", filters.frontierSampled);
    if (filters.disagreement) params.set("disagreement", "true");
    if (selected) params.set("trace", selected);
    const qs = params.toString();
    window.history.replaceState(
      null,
      "",
      qs ? `/investigations?${qs}` : "/investigations",
    );
  }, [filters, selected]);

  function handleFiltersChange(next: InvestigationsFilterState) {
    setFilters(next);
    setOffset(0);
  }

  useEffect(() => {
    let cancelled = false;
    const qs = buildQuery({ ...filters, q: debouncedQ }, offset);
    fetch(`${GATEWAY_URL}/ops/traces?${qs}`)
      .then((res) => {
        if (!res.ok) {
          throw new Error(
            `Trace service unavailable. The gateway returned ${res.status}.`,
          );
        }
        return res.json() as Promise<TraceListResponse>;
      })
      .then((body) => {
        if (!cancelled) {
          setData(body);
          setStatus("ready");
          setFetching(false);
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setErrorMessage(
            err instanceof Error ? err.message : "Trace service unreachable.",
          );
          setStatus("error");
          setFetching(false);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [filters, debouncedQ, offset, retryToken]);

  const filtered = hasActiveFilters(filters);

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-12 sm:px-8 sm:py-16">
      <PageHeader eyebrow="Forensic workspace" title="Investigations">
        One row per persisted execution. Nothing here is grouped, sampled or
        deduplicated. Open a row for the evidence behind it.
      </PageHeader>

      <div className="mt-10">
        <InvestigationsFilters
          filters={filters}
          onChange={(next) => {
            setFetching(true);
            handleFiltersChange(next);
          }}
        />
      </div>

      <div className="mt-6">
        <AsyncState
          status={status}
          errorMessage={errorMessage}
          onRetry={() => {
            setStatus("loading");
            setFetching(true);
            setRetryToken((n) => n + 1);
          }}
        >
          {!data || data.traces.length === 0 ? (
            <div className="border-border-strong rounded-xl border border-dashed px-6 py-14 text-center">
              <p className="text-text-primary text-lg font-medium">
                {filtered
                  ? "No executions match these filters."
                  : "No executions are persisted yet."}
              </p>
              {filtered ? (
                <button
                  type="button"
                  onClick={() => {
                    setFetching(true);
                    handleFiltersChange(EMPTY_FILTERS);
                  }}
                  className="border-border-strong text-text-primary hover:bg-surface mt-5 min-h-11 rounded-lg border px-4 text-sm font-medium"
                >
                  Clear all filters
                </button>
              ) : null}
            </div>
          ) : (
            <>
              <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
                <p className="text-text-secondary text-sm" aria-live="polite">
                  Showing {offset + 1}–{offset + data.traces.length}
                  {data.next_offset === null ? " (end of results)" : ""}.
                </p>
                {filtered ? (
                  <button
                    type="button"
                    onClick={() => {
                      setFetching(true);
                      handleFiltersChange(EMPTY_FILTERS);
                    }}
                    className="text-accent hover:text-text-primary min-h-11 px-2 text-sm underline underline-offset-4"
                  >
                    Clear all filters
                  </button>
                ) : null}
              </div>
              <InvestigationsTable
                traces={data.traces}
                onSelect={setSelected}
                selectedTraceId={selected}
                disagreementIds={disagreementIds}
                busy={fetching}
              />
              <div className="mt-6 flex items-center gap-3">
                <button
                  type="button"
                  disabled={offset === 0}
                  onClick={() => {
                    setFetching(true);
                    setOffset((o) => Math.max(0, o - PAGE_SIZE));
                  }}
                  className="border-border-strong text-text-primary hover:bg-surface min-h-11 rounded-lg border px-4 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Previous
                </button>
                <button
                  type="button"
                  disabled={data.next_offset === null}
                  onClick={() => {
                    setFetching(true);
                    setOffset(data.next_offset ?? offset);
                  }}
                  className="border-border-strong text-text-primary hover:bg-surface min-h-11 rounded-lg border px-4 text-sm font-medium disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Next
                </button>
              </div>
            </>
          )}
        </AsyncState>
      </div>

      {selected ? (
        <TraceDrilldown
          key={selected}
          appTraceId={selected}
          onClose={() => setSelected(null)}
        />
      ) : null}
    </div>
  );
}
