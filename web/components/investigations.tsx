"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { AsyncState, type AsyncStatus } from "@/components/async-state";
import {
  InvestigationsFilters,
  type InvestigationsFilterState,
} from "@/components/investigations-filters";
import { InvestigationsTable } from "@/components/investigations-table";
import { TraceDrilldown } from "@/components/trace-drilldown";
import { GATEWAY_URL } from "@/lib/config";
import type { TraceListResponse } from "@/lib/trace-api";

const PAGE_SIZE = 50;

const EMPTY_FILTERS: InvestigationsFilterState = {
  q: "",
  ticker: "",
  ragStatus: "",
  judgeState: "",
  frontierSampled: "",
  disagreement: false,
};

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
 * The real investigation workspace (renamed from Judge Panel). Search,
 * filters, the frontier/flash disagreement lens, and real server-side
 * pagination over the full dataset -- never the hardcoded 50-row window
 * the Day 9 Session 1 build shipped.
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
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [retryToken, setRetryToken] = useState(0);
  const [selected, setSelected] = useState<string | null>(
    searchParams.get("trace"),
  );

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
            `Trace service unavailable — gateway returned ${res.status}`,
          );
        }
        return res.json() as Promise<TraceListResponse>;
      })
      .then((body) => {
        if (!cancelled) {
          setData(body);
          setStatus("ready");
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setErrorMessage(
            err instanceof Error ? err.message : "Trace service unreachable.",
          );
          setStatus("error");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [filters, debouncedQ, offset, retryToken]);

  return (
    <div className="mx-auto w-full max-w-5xl px-4 py-8 sm:px-6">
      <h1 className="text-text-primary text-3xl font-semibold tracking-tight">
        Investigations
      </h1>
      <p className="text-text-secondary mt-1.5 max-w-2xl text-sm">
        Every persisted request, individually -- never grouped or deduplicated.
        Search, filter, or open the disagreement lens below, then select a row
        for the full trace evidence.
      </p>

      <div className="mt-6">
        <InvestigationsFilters
          filters={filters}
          onChange={handleFiltersChange}
        />
      </div>

      <div className="mt-4">
        <AsyncState
          status={status}
          errorMessage={errorMessage}
          onRetry={() => {
            setStatus("loading");
            setRetryToken((n) => n + 1);
          }}
        >
          {!data || data.traces.length === 0 ? (
            <p className="text-text-secondary text-sm">
              No traces match these filters.
            </p>
          ) : (
            <>
              <p className="text-text-secondary mb-2 text-xs">
                Showing {offset + 1}–{offset + data.traces.length}
                {data.next_offset === null ? " (end of results)" : ""}.
              </p>
              <InvestigationsTable
                traces={data.traces}
                onSelect={setSelected}
                selectedTraceId={selected}
              />
              <div className="mt-3 flex items-center gap-2">
                <button
                  type="button"
                  disabled={offset === 0}
                  onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
                  className="border-border hover:bg-surface min-h-11 rounded-md border px-3 text-sm disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Previous
                </button>
                <button
                  type="button"
                  disabled={data.next_offset === null}
                  onClick={() => setOffset(data.next_offset ?? offset)}
                  className="border-border hover:bg-surface min-h-11 rounded-md border px-3 text-sm disabled:cursor-not-allowed disabled:opacity-40"
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
