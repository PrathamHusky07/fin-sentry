"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { ARCHIVE_MODE, ARCHIVE_READ_ONLY } from "@/lib/archive-mode";
import { TRIGGER_LABEL, type TriggerKind } from "@/lib/incidents";
import {
  IncidentApiError,
  startIncident,
  type StartRequest,
} from "@/lib/incidents-api";
import { RunPasswordField } from "@/components/run-password-field";

const KINDS = Object.keys(TRIGGER_LABEL) as TriggerKind[];
const NEEDS_REFERENCE: Partial<Record<TriggerKind, string>> = {
  single_trace: "Trace id",
  red_team_miss: "Red Team execution id",
};
const WINDOWS = [15, 60, 240, 1440];

const FIELD =
  "border-border-strong bg-background-elevated text-text-primary focus-visible:outline-accent min-h-11 w-full rounded-lg border px-3 text-base";

/**
 * Starts one investigation of the live platform. The investigation reads through the nine
 * read-only tools and asks the planner for hypotheses at most twice. The page says what that
 * costs and guards, and an identical request made while one runs opens the running one
 * instead of starting a second. When the gateway did not answer, the form is not offered at all:
 * an action that cannot run is shown as unavailable and never as a form that fails on submit.
 */
function StartIncidentForm() {
  const router = useRouter();
  const [kind, setKind] = useState<TriggerKind>("drift_degradation");
  const [reference, setReference] = useState("");
  const [ticker, setTicker] = useState("");
  const [minutes, setMinutes] = useState(60);
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<{
    text: string;
    id: string | null;
  } | null>(null);
  const referenceLabel = NEEDS_REFERENCE[kind];

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    setNotice(null);
    const body: StartRequest = { kind, window_minutes: minutes };
    if (referenceLabel) body.reference_id = reference.trim();
    if (ticker.trim()) body.ticker = ticker.trim().toUpperCase();
    try {
      const started = await startIncident(body, password);
      if (started.created) {
        router.push(`/agent/${started.investigation.investigation_id}`);
        return;
      }
      setNotice({
        text: "An identical investigation is already running. It was not started again.",
        id: started.investigation.investigation_id,
      });
    } catch (err: unknown) {
      const text = err instanceof Error ? err.message : "The request failed.";
      setNotice({
        text,
        id: err instanceof IncidentApiError ? err.investigationId : null,
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <details className="border-border bg-background-elevated/60 group rounded-xl border">
      <summary className="text-text-primary flex min-h-12 cursor-pointer items-center justify-between gap-3 px-5 text-base font-medium">
        Start an investigation of the live platform
        <span
          aria-hidden="true"
          className="text-text-tertiary transition-transform group-open:rotate-90"
        >
          →
        </span>
      </summary>
      <form
        onSubmit={submit}
        className="border-border space-y-5 border-t px-5 py-5"
      >
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <label className="block">
            <span className="text-text-secondary text-sm">
              What triggered it
            </span>
            <select
              className={`${FIELD} mt-1`}
              value={kind}
              onChange={(e) => setKind(e.target.value as TriggerKind)}
            >
              {KINDS.map((k) => (
                <option key={k} value={k}>
                  {TRIGGER_LABEL[k]}
                </option>
              ))}
            </select>
          </label>
          {referenceLabel ? (
            <label className="block">
              <span className="text-text-secondary text-sm">
                {referenceLabel}
              </span>
              <input
                className={`${FIELD} mt-1 font-mono`}
                value={reference}
                onChange={(e) => setReference(e.target.value)}
                name="reference_id"
                autoComplete="off"
                spellCheck={false}
                required
                maxLength={100}
              />
            </label>
          ) : null}
          <label className="block">
            <span className="text-text-secondary text-sm">
              Ticker (optional)
            </span>
            <input
              className={`${FIELD} mt-1 font-mono uppercase`}
              value={ticker}
              onChange={(e) => setTicker(e.target.value)}
              name="ticker"
              autoComplete="off"
              spellCheck={false}
              maxLength={12}
            />
          </label>
          <label className="block">
            <span className="text-text-secondary text-sm">Look back</span>
            <select
              className={`${FIELD} mt-1`}
              value={minutes}
              onChange={(e) => setMinutes(Number(e.target.value))}
            >
              {WINDOWS.map((w) => (
                <option key={w} value={w}>
                  {w >= 60
                    ? `${w / 60} ${w === 60 ? "hour" : "hours"}`
                    : `${w} minutes`}
                </option>
              ))}
            </select>
          </label>
        </div>
        <RunPasswordField
          value={password}
          onChange={setPassword}
          disabled={busy}
        />
        <p className="text-text-secondary max-w-3xl text-base leading-relaxed">
          The investigator reads the platform through nine read-only tools and
          cannot change anything. It asks the model for hypotheses at most
          twice. Before each model call the worst-case cost is reserved against
          a session cap, and a call that could pass the cap is refused. The
          result is stored, and opening it again never runs it again.
        </p>
        <div className="flex flex-wrap items-center gap-4">
          <button
            type="submit"
            disabled={busy || password === ""}
            className="bg-accent text-background min-h-11 rounded-lg px-5 text-base font-medium disabled:opacity-50"
          >
            {busy ? "Starting…" : "Start investigation"}
          </button>
          {notice ? (
            <p role="status" className="text-text-primary text-base">
              {notice.text}{" "}
              {notice.id ? (
                <Link
                  href={`/agent/${notice.id}`}
                  className="text-accent underline underline-offset-4"
                >
                  Open the running one
                </Link>
              ) : null}
            </p>
          ) : null}
        </div>
      </form>
    </details>
  );
}

export function StartIncidentUnavailable() {
  return (
    <div
      data-start-incident="unavailable"
      className="border-border bg-background-elevated/40 rounded-xl border px-5 py-4"
    >
      <p className="text-text-primary text-base font-medium">
        Starting an investigation is unavailable
      </p>
      <p className="text-text-secondary mt-1 max-w-3xl text-base leading-relaxed">
        {ARCHIVE_MODE
          ? ARCHIVE_READ_ONLY
          : "It runs against the live backend, and the gateway did not answer, so nothing can be started from here."}
      </p>
    </div>
  );
}

export function StartIncident({ available }: { available: boolean }) {
  return available && !ARCHIVE_MODE ? (
    <StartIncidentForm />
  ) : (
    <StartIncidentUnavailable />
  );
}
