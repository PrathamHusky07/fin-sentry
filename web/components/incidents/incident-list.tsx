"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AsyncState, type AsyncStatus } from "@/components/async-state";
import {
  OriginBadge,
  OutcomeBadge,
  StatusBadge,
  SubsystemChip,
} from "@/components/incidents/badges";
import { StartIncident } from "@/components/incidents/start-incident";
import { ViewSwitch } from "@/components/incidents/view-switch";
import { PageHeader } from "@/components/page-header";
import { relativeTime } from "@/lib/format";
import {
  STOPPING_LABEL,
  TRIGGER_LABEL,
  type Status,
  type Summary,
} from "@/lib/incidents";
import { fetchIncidents } from "@/lib/incidents-api";

const FILTERS: { value: Status | ""; label: string }[] = [
  { value: "", label: "All" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
  { value: "interrupted", label: "Interrupted" },
  { value: "running", label: "Running" },
];

function tone(s: Summary): string {
  if (s.status === "failed") return "var(--failure)";
  if (s.status === "interrupted") return "var(--warning)";
  if (s.status === "running") return "var(--accent)";
  return s.outcome === "diagnosis" ? "var(--info)" : "var(--text-tertiary)";
}

function Finding({ s }: { s: Summary }) {
  if (s.status === "failed") {
    return (
      <span className="text-failure text-base">
        The investigator raised an error.
      </span>
    );
  }
  if (s.status === "interrupted") {
    return (
      <span className="text-warning text-base">
        Stopped before it finished.
      </span>
    );
  }
  if (s.status === "running") {
    return (
      <span className="text-text-secondary text-base">Still working.</span>
    );
  }
  if (s.leading) {
    return (
      <span className="flex flex-wrap items-center gap-2">
        <SubsystemChip subsystem={s.leading.subsystem} />
        <span className="text-text-secondary text-sm">
          {s.leading.confidence} confidence, not proven
        </span>
      </span>
    );
  }
  return (
    <span className="text-text-primary text-base">
      No root cause established
    </span>
  );
}

function Meta({ s }: { s: Summary }) {
  const queries =
    s.queries === null ? "queries not stored" : `${s.queries} queries`;
  const model =
    s.model_calls === null
      ? "model use not stored"
      : s.model_calls === 0
        ? "no model call"
        : `${s.model_calls} model ${s.model_calls === 1 ? "call" : "calls"}, $${(s.cost_usd ?? 0).toFixed(4)}`;
  return (
    <span className="text-text-secondary text-sm">
      {queries}, {model}
    </span>
  );
}

function Row({ s }: { s: Summary }) {
  return (
    <li
      className="row-reveal border-border relative border-b"
      style={{ ["--tone" as string]: tone(s) }}
    >
      <div className="grid gap-3 px-4 py-4 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)_minmax(0,1fr)_9rem] lg:items-center lg:gap-6">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge status={s.status} />
            <OutcomeBadge outcome={s.outcome} />
            <OriginBadge origin={s.origin} planner={s.planner} />
          </div>
          <Link
            href={`/investigations/incidents/${s.investigation_id}`}
            className="text-text-primary mt-2 inline-flex min-h-11 items-center text-lg font-medium after:absolute after:inset-0"
          >
            {TRIGGER_LABEL[s.trigger.kind]}
          </Link>
          <p className="text-text-secondary -mt-1 text-base">
            {s.trigger.description}
          </p>
        </div>
        <div>
          <p className="text-text-tertiary text-sm lg:hidden">Finding</p>
          <Finding s={s} />
        </div>
        <div>
          <p className="text-text-tertiary text-sm lg:hidden">Stopped for</p>
          <p className="text-text-primary text-base">
            {s.stopping_reason
              ? STOPPING_LABEL[s.stopping_reason]
              : "Did not reach a decision"}
          </p>
          <Meta s={s} />
        </div>
        <p
          className="text-text-secondary text-sm lg:text-right"
          title={s.created_at}
        >
          {relativeTime(s.created_at)}
        </p>
      </div>
    </li>
  );
}

/**
 * Every stored investigation, newest first. A row is one session of the investigator on one
 * incident. The list reads stored sessions only. Nothing on this page runs an investigation
 * except the start form, and that says what it does before it does it.
 */
export function IncidentList() {
  const [filter, setFilter] = useState<Status | "">("");
  const [rows, setRows] = useState<Summary[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [status, setStatus] = useState<AsyncStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [more, setMore] = useState(false);

  useEffect(() => {
    let cancelled = false;
    fetchIncidents(0, filter)
      .then((page) => {
        if (cancelled) return;
        setRows(page.investigations);
        setNext(page.next_offset);
        setStatus("ready");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(
          err instanceof Error
            ? err.message
            : "The gateway could not be reached.",
        );
        setStatus("error");
      });
    return () => {
      cancelled = true;
    };
  }, [filter, retry]);

  async function loadMore() {
    if (next === null) return;
    setMore(true);
    try {
      const page = await fetchIncidents(next, filter);
      setRows((r) => [...r, ...page.investigations]);
      setNext(page.next_offset);
    } catch (err: unknown) {
      setError(
        err instanceof Error
          ? err.message
          : "The gateway could not be reached.",
      );
      setStatus("error");
    } finally {
      setMore(false);
    }
  }

  return (
    <div className="ctx ctx-forensic flex-1">
      <div className="mx-auto w-full max-w-7xl px-4 py-12 sm:px-8 sm:py-16">
        <PageHeader
          eyebrow="Which incident was examined, and what did the investigator find?"
          title="Incident investigations"
          aside={
            <div className="flex flex-col items-start gap-1 lg:items-end">
              <ViewSwitch current="incidents" />
              <Link
                href="/architecture#incident-investigator"
                className="text-accent hover:text-text-primary inline-flex min-h-11 items-center text-sm underline underline-offset-4"
              >
                How the investigator works
              </Link>
            </div>
          }
        >
          Each row is one stored session of the reliability investigator on one
          incident: what triggered it, which hypotheses competed, and whether it
          found a best-supported cause or said it could not. Opening a row reads
          the stored session and runs nothing.
        </PageHeader>

        <div className="mt-8">
          <StartIncident />
        </div>

        <div
          className="mt-8 flex flex-wrap items-center gap-2"
          role="group"
          aria-label="Filter by status"
        >
          {FILTERS.map((f) => (
            <button
              key={f.value}
              type="button"
              aria-pressed={filter === f.value}
              onClick={() => {
                setStatus("loading");
                setFilter(f.value);
              }}
              className={`min-h-11 rounded-lg border px-4 text-sm ${filter === f.value ? "border-line-active bg-surface-high text-text-primary" : "border-border-strong text-text-secondary hover:text-text-primary"}`}
            >
              {f.label}
            </button>
          ))}
        </div>

        <div className="mt-4">
          <AsyncState
            status={status}
            errorMessage={error}
            onRetry={() => {
              setStatus("loading");
              setRetry((n) => n + 1);
            }}
            loadingLabel="Loading stored investigations"
          >
            {rows.length === 0 ? (
              <div className="border-border-strong rounded-xl border border-dashed px-6 py-14 text-center">
                <p className="text-text-primary text-lg font-medium">
                  {filter
                    ? "No stored investigation has this status."
                    : "No investigation is stored yet."}
                </p>
                <p className="text-text-secondary mx-auto mt-2 max-w-xl text-base">
                  A stored session appears here after an investigation is
                  started and finishes or stops.
                </p>
              </div>
            ) : (
              <>
                <ul className="border-border border-t">
                  {rows.map((s) => (
                    <Row key={s.investigation_id} s={s} />
                  ))}
                </ul>
                {next !== null ? (
                  <button
                    type="button"
                    onClick={loadMore}
                    disabled={more}
                    className="border-border-strong text-text-primary hover:bg-surface mt-4 min-h-11 rounded-lg border px-4 text-sm font-medium disabled:opacity-50"
                  >
                    {more ? "Loading…" : "Load older investigations"}
                  </button>
                ) : (
                  <p className="text-text-tertiary mt-4 text-sm">
                    End of stored investigations.
                  </p>
                )}
              </>
            )}
          </AsyncState>
        </div>
      </div>
    </div>
  );
}
