"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { OriginBadge } from "@/components/incidents/badges";
import { relativeTime } from "@/lib/format";
import { sessionsForExecution, type Summary } from "@/lib/incidents";
import { IncidentApiError, startIncident } from "@/lib/incidents-api";
import {
  OUTCOME_LABEL,
  type ExecutionRecord,
  expectationLabel,
} from "@/lib/red-team";

const BUTTON =
  "min-h-11 rounded-lg border px-4 text-base font-medium sm:text-sm disabled:cursor-not-allowed disabled:opacity-50";

/** What the investigation reads back to the agent, as a request. The window only bounds the
 * agent's queries about live traffic. The trigger names the execution. */
const WINDOW_MINUTES = 1440;

/**
 * Opens an incident investigation on one Red Team execution through the existing
 * red_team_miss trigger and the existing bounded API, then lands on the Agent detail page.
 * A stored investigation of the same execution is offered first, because opening one costs
 * nothing. Starting a new one is explicit, says what it does and what it can spend, and is
 * never triggered by a render, a refresh or a hover.
 *
 * `sessions` is null when the stored sessions could not be read. The control then says so and
 * does not claim that none exist.
 */
export function InvestigateThis({
  execution,
  sessions,
  onStarted,
}: {
  execution: ExecutionRecord;
  sessions: Summary[] | null;
  onStarted?: () => void;
}) {
  const router = useRouter();
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{
    text: string;
    id: string | null;
  } | null>(null);
  const stored =
    sessions === null
      ? []
      : sessionsForExecution(sessions, execution.execution_id);

  async function start() {
    setBusy(true);
    setNotice(null);
    try {
      const started = await startIncident({
        kind: "red_team_miss",
        reference_id: execution.execution_id,
        window_minutes: WINDOW_MINUTES,
      });
      onStarted?.();
      if (started.created) {
        router.push(`/agent/${started.investigation.investigation_id}`);
        return;
      }
      setNotice({
        text: "An identical investigation is already running. It was not started again.",
        id: started.investigation.investigation_id,
      });
    } catch (err: unknown) {
      setNotice({
        text: err instanceof Error ? err.message : "The request failed.",
        id: err instanceof IncidentApiError ? err.investigationId : null,
      });
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  }

  return (
    <div className="space-y-3">
      {stored.length > 0 ? (
        <ul
          className="space-y-2"
          aria-label="Stored investigations of this execution"
        >
          {stored.map((s) => (
            <li key={s.investigation_id}>
              <Link
                href={`/agent/${s.investigation_id}`}
                className="border-info/40 bg-info/5 text-text-primary hover:bg-info/10 flex min-h-11 flex-wrap items-center gap-x-3 gap-y-1 rounded-lg border px-4 py-2 text-base sm:text-sm"
              >
                <span className="font-medium">
                  Open the stored investigation
                </span>
                <OriginBadge origin={s.origin} planner={s.planner} />
                <span className="text-text-secondary">
                  {s.status === "completed"
                    ? s.outcome === "diagnosis"
                      ? "best-supported hypothesis"
                      : "abstained"
                    : s.status}
                  , {relativeTime(s.created_at)}
                </span>
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
      {sessions === null ? (
        <p className="text-text-secondary text-base sm:text-sm">
          Stored investigations could not be read, so this cannot say whether
          one exists.
        </p>
      ) : null}

      {confirming ? (
        <div
          role="group"
          aria-label="Confirm starting an investigation"
          className="border-signal/40 bg-signal/5 max-w-xl rounded-lg border p-4"
        >
          <p className="text-text-primary text-base leading-relaxed">
            This starts a live investigation of the platform on{" "}
            {execution.scenario_id}, a result that was{" "}
            {OUTCOME_LABEL[execution.outcome ?? "missed"].toLowerCase()} and{" "}
            {expectationLabel(execution).toLowerCase()}. The agent reads through
            nine read-only tools and asks the model for hypotheses at most
            twice. Each call’s worst-case cost is reserved against a $0.10
            session cap first. The result is stored and opens in the Agent.
          </p>
          <div className="mt-3 flex flex-wrap gap-2">
            <button
              type="button"
              disabled={busy}
              onClick={() => void start()}
              className={`${BUTTON} border-signal/60 text-text-primary hover:bg-signal/10`}
            >
              {busy ? "Starting…" : "Start investigation"}
            </button>
            <button
              type="button"
              disabled={busy}
              onClick={() => setConfirming(false)}
              className={`${BUTTON} border-border-strong text-text-primary hover:bg-surface`}
            >
              Cancel
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          onClick={() => setConfirming(true)}
          className={`${BUTTON} border-border-strong text-text-primary hover:bg-surface`}
        >
          {stored.length > 0 ? "Investigate again" : "Investigate this"}
        </button>
      )}

      {notice ? (
        <p role="status" className="text-text-primary text-base sm:text-sm">
          {notice.text}{" "}
          {notice.id ? (
            <Link
              href={`/agent/${notice.id}`}
              className="text-accent inline-flex min-h-11 items-center underline underline-offset-4"
            >
              Open the running one
            </Link>
          ) : null}
        </p>
      ) : null}
    </div>
  );
}
