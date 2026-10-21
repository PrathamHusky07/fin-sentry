import Link from "next/link";
import { CopyButton } from "@/components/copy-button";
import {
  OriginBadge,
  OutcomeBadge,
  StatusBadge,
} from "@/components/incidents/badges";
import { RECORD_STATE, recordStateOf } from "@/lib/agent-view";
import { formatUtc, formatUtcSeconds, relativeTime } from "@/lib/format";
import {
  TRIGGER_LABEL,
  durationLabel,
  windowMinutes,
  type Detail,
} from "@/lib/incidents";

function Fact({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="min-w-0">
      <dt className="text-text-tertiary text-sm">{label}</dt>
      <dd className="text-text-primary mt-0.5 text-base break-words">
        {children}
      </dd>
    </div>
  );
}

function scopeText(d: Detail): string {
  const parts = [
    d.scope.endpoint ? `endpoint ${d.scope.endpoint}` : null,
    d.scope.ticker ? `ticker ${d.scope.ticker}` : null,
  ].filter((p): p is string => p !== null);
  return parts.length > 0
    ? parts.join(", ")
    : "No endpoint or ticker was named, so the whole platform in the window";
}

/** DERIVED. Where the record that triggered a live session can be opened. A fixture session
 * names a record that exists only inside a replayed case world, so it links nowhere. */
function triggerSource(d: Detail): { href: string; label: string } | null {
  const id = d.trigger.reference_id;
  if (d.origin !== "live" || !id) return null;
  if (d.trigger.kind === "red_team_miss") {
    return {
      href: `/red-team?execution=${encodeURIComponent(id)}`,
      label: "Open the execution in Red Team",
    };
  }
  if (d.trigger.kind === "single_trace") {
    return {
      href: `/investigations?trace=${encodeURIComponent(id)}`,
      label: "Open the trace",
    };
  }
  return null;
}

/** What triggered this investigation and what it was asked to look at, from the stored
 * request. Every field here is persisted as the request was accepted. */
export function IncidentHeader({ detail: d }: { detail: Detail }) {
  const minutes = windowMinutes(d.window);
  const source = triggerSource(d);
  return (
    <header>
      <Link
        href="/agent"
        className="text-text-secondary hover:text-text-primary -ml-2 inline-flex min-h-11 items-center gap-2 px-2 text-sm"
      >
        <span aria-hidden="true">←</span> All investigations
      </Link>
      <p className="eyebrow mt-4">Incident {d.incident_id}</p>
      <h1 className="text-text-primary mt-2 max-w-4xl text-3xl font-semibold tracking-tight text-balance sm:text-5xl">
        {TRIGGER_LABEL[d.trigger.kind]}
      </h1>
      <p className="text-text-secondary mt-3 max-w-3xl text-base leading-relaxed text-pretty">
        {d.trigger.description}
        {d.trigger.description.endsWith(".") ? "" : "."}
      </p>

      <div className="mt-5 flex flex-wrap items-center gap-2">
        <StatusBadge status={d.status} withMeaning />
        <OutcomeBadge outcome={d.outcome} />
        <OriginBadge origin={d.origin} planner={d.planner} withMeaning />
        <Link
          href="/architecture#incident-response-agent"
          className="text-accent hover:text-text-primary inline-flex min-h-11 items-center px-1 text-sm underline underline-offset-4"
        >
          How the agent works
        </Link>
      </div>

      <p
        data-record-state={recordStateOf(d.origin)}
        className={`mt-4 max-w-3xl border-l-2 pl-4 text-base leading-relaxed ${d.origin === "live" ? "border-signal/60" : "border-disagreement/60 border-dashed"} text-text-secondary`}
      >
        <span className="text-text-primary font-medium">
          {RECORD_STATE[recordStateOf(d.origin)].label}.
        </span>{" "}
        {RECORD_STATE[recordStateOf(d.origin)].meaning}
      </p>

      {d.stale ? (
        <p
          role="status"
          className="border-warning/50 bg-warning/5 text-text-primary mt-5 max-w-3xl rounded-lg border border-dashed px-4 py-3 text-base"
        >
          This investigation stored no event for{" "}
          {relativeTime(d.heartbeat_at).replace(" ago", "")}. The process
          running it may have stopped. A new investigation start will mark it
          interrupted.
        </p>
      ) : null}
      {d.status === "running" && !d.stale ? (
        <p
          role="status"
          className="border-accent/40 bg-accent/5 text-text-primary mt-5 max-w-3xl rounded-lg border px-4 py-3 text-base"
        >
          Still running. This page re-reads the stored session every two seconds
          and shows only what has been stored so far.
        </p>
      ) : null}

      <dl className="border-border mt-8 grid gap-x-8 gap-y-5 border-t pt-6 sm:grid-cols-2 lg:grid-cols-4">
        <Fact label="Triggered by">
          {TRIGGER_LABEL[d.trigger.kind]}
          {d.trigger.reference_id ? (
            <span className="text-text-secondary block font-mono text-base break-all sm:text-sm">
              {d.trigger.reference_id}
            </span>
          ) : null}
          {source ? (
            <Link
              href={source.href}
              className="text-accent hover:text-text-primary inline-flex min-h-11 items-center text-base underline underline-offset-4 sm:text-sm"
            >
              {source.label}
            </Link>
          ) : null}
        </Fact>
        <Fact label="Scope">{scopeText(d)}</Fact>
        <Fact label="Time window">
          {formatUtc(d.window.start)} to {formatUtc(d.window.end)}
          <span className="text-text-secondary block text-sm">
            {minutes} {minutes === 1 ? "minute" : "minutes"} ending when the
            request was accepted
          </span>
        </Fact>
        <Fact label="Planner">
          <span className="font-mono text-sm break-all">{d.planner}</span>
        </Fact>
        <Fact label="Started">{formatUtcSeconds(d.created_at)} UTC</Fact>
        <Fact label="Finished">
          {d.finished_at
            ? `${formatUtcSeconds(d.finished_at)} UTC`
            : "Not finished"}
          <span className="text-text-secondary block text-sm">
            {durationLabel(d.created_at, d.finished_at)}
          </span>
        </Fact>
        <Fact label="Investigation id">
          <span className="flex flex-wrap items-center gap-2">
            <span className="font-mono text-xs break-all">
              {d.investigation_id}
            </span>
            <CopyButton
              value={d.investigation_id}
              label="Copy investigation id"
            />
          </span>
        </Fact>
      </dl>
    </header>
  );
}
