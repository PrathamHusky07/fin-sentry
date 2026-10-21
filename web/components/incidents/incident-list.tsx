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
import { relativeTime } from "@/lib/format";
import {
  STOPPING_LABEL,
  TRIGGER_LABEL,
  tallySessions,
  type Origin,
  type SessionTally,
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
        <span className="text-text-secondary text-base sm:text-sm">
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
    s.queries === null
      ? "queries not stored"
      : `${s.queries} ${s.queries === 1 ? "query" : "queries"}`;
  const model =
    s.model_calls === null
      ? "model use not stored"
      : s.model_calls === 0
        ? "no model call"
        : `${s.model_calls} model ${s.model_calls === 1 ? "call" : "calls"}, $${(s.cost_usd ?? 0).toFixed(4)}`;
  return (
    <span className="text-text-secondary text-base sm:text-sm">
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
            href={`/agent/${s.investigation_id}`}
            className="text-text-primary mt-2 inline-flex min-h-11 items-center text-lg font-medium after:absolute after:inset-0"
          >
            {TRIGGER_LABEL[s.trigger.kind]}
          </Link>
          <p className="text-text-secondary -mt-1 text-base">
            {s.trigger.description}
          </p>
        </div>
        <div>
          <p className="text-text-tertiary text-base lg:hidden">Finding</p>
          <Finding s={s} />
        </div>
        <div>
          <p className="text-text-tertiary text-base lg:hidden">Stopped for</p>
          <p className="text-text-primary text-base">
            {s.stopping_reason
              ? STOPPING_LABEL[s.stopping_reason]
              : "Did not reach a decision"}
          </p>
          <Meta s={s} />
        </div>
        <p
          className="text-text-secondary text-base sm:text-sm lg:text-right"
          title={s.created_at}
        >
          {relativeTime(s.created_at)}
        </p>
      </div>
    </li>
  );
}

const ORIGINS: { value: Origin | ""; label: string }[] = [
  { value: "", label: "Live and fixture" },
  { value: "live", label: "Live platform" },
  { value: "fixture", label: "Fixture replay" },
];

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
      : `${t.live} ran on the live platform and ${t.fixture} ${t.fixture === 1 ? "is a fixture replay" : "are fixture replays"}.`,
  );
  return parts.join(" ");
}

const CHIP =
  "min-h-11 rounded-lg border px-4 text-base sm:text-sm transition-colors";

/**
 * Every stored investigation, newest first. A row is one session of the agent on one incident.
 * The list reads stored sessions only. Nothing here runs an investigation except the start
 * form, and that says what it does before it does it. The origin filter works on the rows
 * already loaded, because the API filters by status only.
 */
export function IncidentList() {
  const [filter, setFilter] = useState<Status | "">("");
  const [origin, setOrigin] = useState<Origin | "">("");
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

  const shown = origin ? rows.filter((r) => r.origin === origin) : rows;

  return (
    <div>
      <AsyncState
        status={status}
        errorMessage={error}
        onRetry={() => {
          setStatus("loading");
          setRetry((n) => n + 1);
        }}
        loadingLabel="Loading stored investigations"
      >
        {!filter && rows.length > 0 ? (
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
            {FILTERS.map((f) => (
              <button
                key={f.value}
                type="button"
                aria-pressed={filter === f.value}
                onClick={() => {
                  setStatus("loading");
                  setFilter(f.value);
                }}
                className={`${CHIP} ${filter === f.value ? "border-line-active bg-surface-high text-text-primary" : "border-border-strong text-text-secondary hover:text-text-primary"}`}
              >
                {f.label}
              </button>
            ))}
          </div>
          <div
            className="flex flex-wrap items-center gap-2"
            role="group"
            aria-label="Filter by origin"
          >
            {ORIGINS.map((o) => (
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

        <div className="mt-4">
          {shown.length === 0 ? (
            <div className="border-border-strong rounded-xl border border-dashed px-6 py-14 text-center">
              <p className="text-text-primary text-lg font-medium">
                {filter || origin
                  ? "No loaded investigation matches these filters."
                  : "No investigation is stored yet."}
              </p>
              <p className="text-text-secondary mx-auto mt-2 max-w-xl text-base">
                {origin && next !== null
                  ? "Older stored sessions are not loaded yet. Load more to look further back."
                  : "A stored session appears here after an investigation is started and finishes or stops."}
              </p>
            </div>
          ) : (
            <ul className="border-border border-t">
              {shown.map((s) => (
                <Row key={s.investigation_id} s={s} />
              ))}
            </ul>
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
        </div>
      </AsyncState>
    </div>
  );
}
