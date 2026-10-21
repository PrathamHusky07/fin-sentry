"use client";

import { useEffect, useState } from "react";
import { AsyncState, type AsyncStatus } from "@/components/async-state";
import { CaseBrief } from "@/components/agent/case-brief";
import {
  OriginBadge,
  OutcomeBadge,
  StatusBadge,
} from "@/components/incidents/badges";
import { relativeTime } from "@/lib/format";
import {
  TRIGGER_LABEL,
  tallySessions,
  type Origin,
  type SessionTally,
  type Status,
  type Summary,
} from "@/lib/incidents";
import { fetchIncidents } from "@/lib/incidents-api";
import { useIsDesktop } from "@/lib/use-is-desktop";

const PAGE = 50;

const STATUS_FILTERS: { value: Status | ""; label: string }[] = [
  { value: "", label: "All" },
  { value: "completed", label: "Completed" },
  { value: "failed", label: "Failed" },
  { value: "interrupted", label: "Interrupted" },
];

const ORIGIN_FILTERS: { value: Origin | ""; label: string }[] = [
  { value: "", label: "All records" },
  { value: "live", label: "Live execution" },
  { value: "fixture", label: "Fixture replay" },
];

function tone(s: Summary): string {
  if (s.status === "failed") return "var(--failure)";
  if (s.status === "interrupted") return "var(--warning)";
  if (s.status === "running") return "var(--accent)";
  return s.outcome === "diagnosis" ? "var(--info)" : "var(--text-tertiary)";
}

/** The one line a row says about its result. A failed or interrupted session is never
 * described as a finding, and a best-supported hypothesis is never called a cause. */
function finding(s: Summary): { text: string; cls: string } {
  if (s.status === "failed") {
    return { text: "The investigator raised an error", cls: "text-failure" };
  }
  if (s.status === "interrupted") {
    return { text: "Stopped before it finished", cls: "text-warning" };
  }
  if (s.status === "running") {
    return { text: "Still working", cls: "text-text-secondary" };
  }
  if (s.leading) {
    return {
      text: `Best-supported hypothesis, ${s.leading.confidence} confidence, not proven`,
      cls: "text-text-primary",
    };
  }
  return { text: "No root cause established", cls: "text-text-primary" };
}

function plural(n: number, one: string, many = `${one}s`): string {
  return `${n} ${n === 1 ? one : many}`;
}

/** The one sentence a viewer reads first, from the loaded sessions only. It never calls a
 * failed or unfinished session a result, and it says how many are fixtures. */
function headline(t: SessionTally, more: boolean): string {
  const parts = [
    `${plural(t.total, "stored investigation")}${more ? " loaded, with older ones still stored" : ""}.`,
  ];
  const finished = [
    t.diagnoses > 0
      ? `${t.diagnoses} named a best-supported cause, not a proven one`
      : null,
    t.abstentions > 0 ? `${t.abstentions} abstained` : null,
  ].filter((x): x is string => x !== null);
  if (finished.length > 0) parts.push(`${finished.join(" and ")}.`);
  const unfinished = [
    t.failed > 0 ? `${t.failed} failed` : null,
    t.interrupted > 0 ? `${t.interrupted} was interrupted` : null,
    t.running > 0 ? `${t.running} still running` : null,
  ].filter((x): x is string => x !== null);
  if (unfinished.length > 0) parts.push(`${unfinished.join(", ")}.`);
  parts.push(
    t.live === 0
      ? "None ran on the live platform. Every one is a fixture replay."
      : `${t.live} ${t.live === 1 ? "is a live execution" : "are live executions"} and ${t.fixture} ${t.fixture === 1 ? "is a fixture replay" : "are fixture replays"}.`,
  );
  return parts.join(" ");
}

const CHIP =
  "min-h-11 rounded-lg border px-4 text-base sm:text-sm transition-colors";

function Row({
  s,
  selected,
  onSelect,
  children,
}: {
  s: Summary;
  selected: boolean;
  onSelect: () => void;
  children?: React.ReactNode;
}) {
  const f = finding(s);
  return (
    <li
      className="row-reveal border-border border-b"
      data-active={selected ? "true" : undefined}
      style={{ ["--tone" as string]: tone(s) }}
    >
      <button
        type="button"
        aria-pressed={selected}
        onClick={onSelect}
        className="grid min-h-11 w-full gap-1.5 px-4 py-4 text-left"
      >
        <span className="flex flex-wrap items-center gap-2">
          <StatusBadge status={s.status} />
          <OutcomeBadge outcome={s.outcome} />
          <OriginBadge origin={s.origin} planner={s.planner} />
          <span
            className="text-text-tertiary ml-auto text-base sm:text-sm"
            title={s.created_at}
          >
            {relativeTime(s.created_at)}
          </span>
        </span>
        <span className="text-text-primary text-lg font-medium">
          {TRIGGER_LABEL[s.trigger.kind]}
        </span>
        <span className="text-text-secondary text-base">
          {s.trigger.description}
        </span>
        <span className={`${f.cls} text-base`}>{f.text}</span>
      </button>
      {children}
    </li>
  );
}

/**
 * The stored investigations as a case explorer: a filterable list of cases and, for the one
 * selected, the first layer of its file. The list reads stored sessions only and filters the
 * loaded rows, so the status and origin controls cost no request. Nothing here runs an
 * investigation. The brief beside the list is a summary from the same rows, and the full
 * case file opens on its own page.
 */
export function CaseExplorer() {
  const desktop = useIsDesktop();
  const [status, setStatus] = useState<Status | "">("");
  const [origin, setOrigin] = useState<Origin | "">("");
  const [rows, setRows] = useState<Summary[]>([]);
  const [next, setNext] = useState<number | null>(null);
  const [load, setLoad] = useState<AsyncStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [retry, setRetry] = useState(0);
  const [more, setMore] = useState(false);
  const [chosen, setChosen] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchIncidents(0, "", PAGE)
      .then((page) => {
        if (cancelled) return;
        setRows(page.investigations);
        setNext(page.next_offset);
        setLoad("ready");
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(
          err instanceof Error
            ? err.message
            : "The gateway could not be reached.",
        );
        setLoad("error");
      });
    return () => {
      cancelled = true;
    };
  }, [retry]);

  async function loadMore() {
    if (next === null) return;
    setMore(true);
    try {
      const page = await fetchIncidents(next, "", PAGE);
      setRows((r) => [...r, ...page.investigations]);
      setNext(page.next_offset);
    } catch (err: unknown) {
      setError(
        err instanceof Error
          ? err.message
          : "The gateway could not be reached.",
      );
      setLoad("error");
    } finally {
      setMore(false);
    }
  }

  const shown = rows.filter(
    (r) => (!status || r.status === status) && (!origin || r.origin === origin),
  );
  const count = (value: Status | "") =>
    rows.filter(
      (r) => (!value || r.status === value) && (!origin || r.origin === origin),
    ).length;
  const running = rows.some((r) => r.status === "running");
  const statusFilters = running
    ? [...STATUS_FILTERS, { value: "running" as const, label: "Running" }]
    : STATUS_FILTERS;
  const selected =
    shown.find((r) => r.investigation_id === chosen) ??
    (desktop ? shown[0] : undefined);

  return (
    <AsyncState
      status={load}
      errorMessage={error}
      onRetry={() => {
        setLoad("loading");
        setRetry((n) => n + 1);
      }}
      loadingLabel="Loading stored investigations"
    >
      {rows.length > 0 ? (
        <p className="text-text-primary max-w-3xl text-lg leading-snug font-medium text-pretty">
          {headline(tallySessions(rows), next !== null)}
        </p>
      ) : null}

      <div className="mt-5 flex flex-wrap items-center gap-x-6 gap-y-3">
        <div
          className="flex flex-wrap items-center gap-2"
          role="group"
          aria-label="Filter by status"
        >
          {statusFilters.map((f) => (
            <button
              key={f.value}
              type="button"
              aria-pressed={status === f.value}
              onClick={() => setStatus(f.value)}
              className={`${CHIP} ${status === f.value ? "border-line-active bg-surface-high text-text-primary" : "border-border-strong text-text-secondary hover:text-text-primary"}`}
            >
              {f.label}
              <span className="text-text-tertiary tabular-metric ml-2">
                {count(f.value)}
              </span>
            </button>
          ))}
        </div>
        <div
          className="flex flex-wrap items-center gap-2"
          role="group"
          aria-label="Filter by record"
        >
          {ORIGIN_FILTERS.map((o) => (
            <button
              key={o.value}
              type="button"
              aria-pressed={origin === o.value}
              onClick={() => setOrigin(o.value)}
              className={`${CHIP} ${origin === o.value ? "border-line-active bg-surface-high text-text-primary" : "border-border-strong text-text-secondary hover:text-text-primary"}`}
            >
              {o.label}
            </button>
          ))}
        </div>
      </div>

      {shown.length === 0 ? (
        <div className="border-border-strong mt-4 rounded-xl border border-dashed px-6 py-14 text-center">
          <p className="text-text-primary text-lg font-medium">
            {status || origin
              ? "No loaded investigation matches these filters."
              : "No investigation is stored yet."}
          </p>
          <p className="text-text-secondary mx-auto mt-2 max-w-xl text-base">
            {(status || origin) && next !== null
              ? "Older stored sessions are not loaded yet. Load more to look further back."
              : "A stored session appears here after an investigation is started and finishes or stops."}
          </p>
        </div>
      ) : (
        <div className="mt-4 grid gap-6 lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)] lg:items-start">
          <ul className="border-border border-t">
            {shown.map((s) => {
              const open = selected?.investigation_id === s.investigation_id;
              return (
                <Row
                  key={s.investigation_id}
                  s={s}
                  selected={open}
                  onSelect={() =>
                    setChosen((cur) =>
                      cur === s.investigation_id && !desktop
                        ? null
                        : s.investigation_id,
                    )
                  }
                >
                  {open && !desktop ? (
                    <div className="swap-in border-border bg-background-elevated/40 border-t px-4 py-5">
                      <CaseBrief summary={s} />
                    </div>
                  ) : null}
                </Row>
              );
            })}
          </ul>
          {desktop && selected ? (
            <div className="lg:sticky lg:top-[calc(var(--nav-h)+4.25rem)]">
              <div
                key={selected.investigation_id}
                style={{ ["--tone" as string]: tone(selected) }}
                className="instrument swap-in bg-background-elevated/60 rounded-xl p-6"
              >
                <CaseBrief summary={selected} />
              </div>
            </div>
          ) : null}
        </div>
      )}

      {next !== null ? (
        <button
          type="button"
          onClick={loadMore}
          disabled={more}
          className="border-border-strong text-text-primary hover:bg-surface mt-4 min-h-11 rounded-lg border px-4 text-base font-medium disabled:opacity-50 sm:text-sm"
        >
          {more ? "Loading…" : "Load older investigations"}
        </button>
      ) : shown.length > 0 ? (
        <p className="text-text-tertiary mt-4 text-base sm:text-sm">
          End of stored investigations.
        </p>
      ) : null}
    </AsyncState>
  );
}
