import { useRef, useState } from "react";
import { Panel } from "@/components/panel";
import { RedTeamOutcomeBadge } from "@/components/red-team-badges";
import { shortId } from "@/lib/format";
import {
  formatCost,
  isSafetyBoundSkip,
  runProgress,
  type RunDetail,
  type ScenarioView,
} from "@/lib/red-team";

const BUTTON =
  "min-h-11 rounded-lg border px-4 text-base font-medium transition-colors sm:text-sm disabled:cursor-not-allowed disabled:opacity-50";

function RunProgress({ detail }: { detail: RunDetail }) {
  const { run } = detail;
  const { finished, total, percent } = runProgress(run);
  const heading =
    run.status === "running"
      ? "Run in progress"
      : run.status === "failed"
        ? "Run failed"
        : "Run finished";
  return (
    <Panel className="mt-4 p-4 sm:p-5" as="section">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="text-text-primary text-base font-medium">{heading}</h3>
        <p className="text-text-tertiary font-mono text-xs">
          Run {shortId(run.run_id)}
        </p>
      </div>
      <div
        role="progressbar"
        aria-label="Executions finished"
        aria-valuemin={0}
        aria-valuemax={total}
        aria-valuenow={finished}
        className="bg-surface mt-3 h-1.5 overflow-hidden rounded-full"
      >
        <div
          className={`h-full transition-[width] ${run.status === "failed" ? "bg-failure" : "bg-accent"}`}
          style={{ width: `${percent}%` }}
        />
      </div>
      <p aria-live="polite" className="text-text-secondary mt-2 text-sm">
        {finished} of {total} executions finished. Read from the stored rows
        every 1.5 seconds while the run is active.
      </p>
      {run.failure_reason ? (
        <p role="alert" className="text-failure mt-2 text-base">
          {run.failure_reason}
        </p>
      ) : null}
      <ul className="mt-3 grid gap-2 sm:grid-cols-2">
        {detail.executions.map((e) => (
          <li
            key={e.execution_id}
            className="border-border flex min-h-11 items-center justify-between gap-3 rounded-md border px-3 py-2"
          >
            <span className="text-text-primary font-mono text-sm">
              {e.scenario_id}
            </span>
            <RedTeamOutcomeBadge
              outcome={e.outcome}
              state={e.state}
              safetyBound={isSafetyBoundSkip(e)}
            />
          </li>
        ))}
      </ul>
    </Panel>
  );
}

/** What a run will do, from the registry. Three facts are structural. A gateway_route scenario
 * posts a real request to the gateway's own /v1/rag/query route in process. The gateway emits
 * one event per request, so it appears in Investigations and in the Live Operations counts. A
 * request no input rail stops goes on to the model path, where the flash judge can call Gemini,
 * and the runner sends at most one such request per run. The other scenarios call the rails
 * directly and publish nothing. */
export function consequences(chosen: ScenarioView[]) {
  const gateway = chosen.filter((s) => s.executor === "gateway_route");
  return {
    total: chosen.length,
    gatewayIds: gateway.map((s) => s.id),
    directCount: chosen.length - gateway.length,
  };
}

function Review({
  chosen,
  judge,
  submitting,
  error,
  onConfirm,
  onCancel,
}: {
  chosen: ScenarioView[];
  judge: boolean;
  submitting: boolean;
  error: string | null;
  onConfirm: (password: string) => void;
  onCancel: () => void;
}) {
  const c = consequences(chosen);
  const only = chosen[0];
  const last = only?.last_execution ?? null;
  // Held only in this component while the review is open. It is sent in a header on submit
  // and never written to the URL, to storage or to a log.
  const [password, setPassword] = useState("");
  // The message belongs to this review only after it has submitted once.
  const [attempted, setAttempted] = useState(false);
  const shown = attempted && !submitting ? error : null;
  const field = useRef<HTMLInputElement>(null);
  return (
    <section
      aria-label="Confirm the run"
      className="border-warning/50 bg-warning/5 mt-4 rounded-xl border p-4 sm:p-5"
    >
      <h4 className="text-text-primary text-base font-semibold">
        Before this run starts
      </h4>
      <ul className="text-text-secondary mt-2 list-disc space-y-1.5 pl-5 text-base leading-relaxed">
        <li>
          It fires {c.total} {c.total === 1 ? "scenario" : "scenarios"} through
          the live defenses, one at a time.
        </li>
        <li>
          It writes {c.total} new execution{" "}
          {c.total === 1 ? "record" : "records"}. Earlier records are kept, and
          each repeat adds to a scenario&rsquo;s history.
        </li>
        {c.gatewayIds.length > 0 ? (
          <li>
            {c.gatewayIds.length} of them ({c.gatewayIds.join(", ")}) send a
            real request to the gateway. It is recorded like any request, so it
            appears in Investigations and in the Live Operations counts. A
            request that no input rail stops continues to the model path, where
            the flash judge can call Gemini at real cost and latency, and those
            calls are not recorded on the execution. A run sends at most one
            such request and skips the rest.
          </li>
        ) : null}
        {c.directCount > 0 ? (
          <li>
            {c.directCount}{" "}
            {c.directCount === 1 ? "scenario calls" : "scenarios call"} the
            rails directly. They publish no event and make no model call.
          </li>
        ) : null}
        {judge ? (
          <li>
            It sends a fixed answer and its context to Gemini and spends model
            calls from the project credit.
            {last
              ? ` The latest stored run made ${last.gemini_calls} ${last.gemini_calls === 1 ? "call" : "calls"} at a recorded ${formatCost(last.cost_usd)}.`
              : " No earlier run is stored, so its cost is not known yet."}
          </li>
        ) : null}
      </ul>
      <form
        className="mt-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (password === "" || submitting) return;
          setAttempted(true);
          onConfirm(password);
          field.current?.select();
        }}
      >
        <label
          htmlFor="run-password"
          className="text-text-primary block text-base font-medium"
        >
          Run password
        </label>
        <p
          id="run-password-help"
          className="text-text-secondary mt-0.5 max-w-prose text-base sm:text-sm"
        >
          Starting a run needs the password the project operator set on the
          gateway. The gateway checks it before anything is created, and a wrong
          one starts nothing.
        </p>
        <input
          ref={field}
          id="run-password"
          name="run-password"
          type="password"
          autoComplete="off"
          spellCheck={false}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          aria-describedby="run-password-help"
          aria-invalid={shown ? true : undefined}
          className="border-border-strong bg-background text-text-primary focus-visible:border-accent mt-2 min-h-11 w-full max-w-xs rounded-lg border px-3 font-mono text-base"
        />
        {shown ? (
          <p role="alert" className="text-failure mt-2 text-base">
            {shown}
          </p>
        ) : null}
        <div className="mt-4 flex flex-wrap gap-3">
          <button
            type="submit"
            disabled={password === "" || submitting}
            className={`${BUTTON} border-warning/70 bg-warning/10 text-text-primary hover:bg-warning/20`}
          >
            {judge ? "Confirm and run" : `Confirm and run ${c.total}`}
          </button>
          <button
            type="button"
            onClick={onCancel}
            disabled={submitting}
            className={`${BUTTON} border-border-strong text-text-primary hover:bg-surface`}
          >
            Cancel
          </button>
        </div>
      </form>
    </section>
  );
}

/**
 * The execution workflow, kept apart from the reading surface. Browsing the console never
 * starts anything. Here a person chooses scenarios, reads what the run will do and confirms,
 * and only the confirmation starts it. One run is active at a time, so every control is
 * disabled while another is in progress. Judge-assisted scenarios are never part of a group,
 * and each runs alone behind the same confirmation.
 */
export function RedTeamExecute({
  scenarios,
  selected,
  onSelectedChange,
  open,
  onOpenChange,
  busy,
  persistenceAvailable,
  runsEnabled,
  activeRun,
  startError,
  onStart,
}: {
  scenarios: ScenarioView[];
  selected: Set<string>;
  onSelectedChange: (next: Set<string>) => void;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  busy: boolean;
  persistenceAvailable: boolean;
  /** False when the gateway has no run password configured, null while that is unknown. */
  runsEnabled: boolean | null;
  activeRun: RunDetail | null;
  startError: string | null;
  /** Resolves true when the gateway accepted the run, false when it refused. */
  onStart: (
    ids: string[] | null,
    judgeAssisted: boolean,
    password: string,
  ) => Promise<boolean>;
}) {
  const [review, setReview] = useState<{
    ids: string[] | null;
    judge: boolean;
  } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const deterministic = scenarios.filter((s) => s.mode === "deterministic");
  const judged = scenarios.filter((s) => s.mode === "judge_assisted");
  const disabled = busy || !persistenceAvailable || runsEnabled === false;
  const reviewChosen = review
    ? review.ids === null
      ? deterministic
      : scenarios.filter((s) => review.ids?.includes(s.id))
    : [];

  function toggle(id: string) {
    const next = new Set(selected);
    if (!next.delete(id)) next.add(id);
    onSelectedChange(next);
  }

  return (
    <div
      className={`rounded-xl border ${open ? "border-warning/40" : "border-border-strong border-dashed"}`}
    >
      <button
        type="button"
        aria-expanded={open}
        aria-controls="execute-body"
        onClick={() => onOpenChange(!open)}
        className="flex min-h-12 w-full items-center justify-between gap-4 px-4 py-3 text-left sm:px-5"
      >
        <span>
          <span className="text-text-primary block text-base font-semibold">
            Run scenarios
          </span>
          <span className="text-text-secondary block text-base sm:text-sm">
            Fires scenarios through the live defenses and writes new execution
            records.
          </span>
        </span>
        <span aria-hidden="true" className="text-text-tertiary">
          {open ? "Hide" : "Open"}
        </span>
      </button>
      {open ? (
        <div id="execute-body" className="border-border border-t p-4 sm:p-5">
          <p className="text-text-secondary max-w-3xl text-base leading-relaxed">
            Nothing on the rest of this page starts a run. Choose scenarios,
            read what the run will do, then confirm. Running a scenario again
            stores a new execution and keeps the earlier one.
          </p>

          <div className="mt-4">
            <p className="text-text-primary text-base font-medium">
              Deterministic scenarios ({deterministic.length})
            </p>
            <ul className="mt-2 grid gap-x-6 sm:grid-cols-2">
              {deterministic.map((s) => (
                <li key={s.id}>
                  <label className="flex min-h-11 cursor-pointer items-center gap-3">
                    <input
                      type="checkbox"
                      checked={selected.has(s.id)}
                      disabled={busy}
                      onChange={() => toggle(s.id)}
                      aria-label={`Select ${s.id}`}
                      className="accent-accent h-5 w-5 shrink-0"
                    />
                    <span className="min-w-0 text-base sm:text-sm">
                      <span className="text-text-primary font-mono">
                        {s.id}
                      </span>
                      <span className="text-text-secondary">
                        {" "}
                        {s.title}
                        {s.executor === "gateway_route"
                          ? ", sends a gateway request"
                          : ""}
                      </span>
                    </span>
                  </label>
                </li>
              ))}
            </ul>
          </div>

          <div className="mt-4 flex flex-wrap items-center gap-3">
            <button
              type="button"
              onClick={() => setReview({ ids: [...selected], judge: false })}
              disabled={disabled || selected.size === 0}
              className={`${BUTTON} border-border-strong text-text-primary hover:bg-surface`}
            >
              Review run of selected ({selected.size})
            </button>
            <button
              type="button"
              onClick={() => setReview({ ids: null, judge: false })}
              disabled={disabled || deterministic.length === 0}
              className={`${BUTTON} border-accent/60 bg-accent/10 text-text-primary hover:bg-accent/20`}
            >
              Review run of all deterministic ({deterministic.length})
            </button>
          </div>

          {judged.length > 0 ? (
            <div className="border-border mt-5 border-t pt-4">
              <p className="text-text-primary text-base font-medium">
                Judge-assisted
              </p>
              <p className="text-text-secondary mt-1 max-w-3xl text-base sm:text-sm">
                These spend Gemini calls, so each runs alone and is never part
                of a group.
              </p>
              <div className="mt-2 flex flex-wrap gap-3">
                {judged.map((s) => (
                  <button
                    key={s.id}
                    type="button"
                    disabled={disabled}
                    onClick={() => setReview({ ids: [s.id], judge: true })}
                    className={`${BUTTON} border-signal/50 text-text-primary hover:bg-signal/10`}
                  >
                    Review run of {s.id} with Gemini judge
                  </button>
                ))}
              </div>
            </div>
          ) : null}

          {review && reviewChosen.length > 0 ? (
            <Review
              chosen={reviewChosen}
              judge={review.judge}
              submitting={submitting}
              error={startError}
              onCancel={() => setReview(null)}
              onConfirm={(password) => {
                const { ids, judge } = review;
                setSubmitting(true);
                void onStart(ids, judge, password)
                  .then((started) => {
                    if (started) setReview(null);
                  })
                  .finally(() => setSubmitting(false));
              }}
            />
          ) : null}

          {busy ? (
            <p
              role="status"
              className="text-text-secondary mt-3 text-base sm:text-sm"
            >
              A run is in progress. Controls return when it ends.
            </p>
          ) : null}
          {!persistenceAvailable ? (
            <p className="text-warning mt-3 text-base sm:text-sm">
              Runs are disabled while the result store is unreachable.
            </p>
          ) : null}
          {runsEnabled === false ? (
            <p role="status" className="text-warning mt-3 text-base sm:text-sm">
              Runs are disabled on this deployment because no run password is
              configured on the gateway. Reading the results still works.
            </p>
          ) : null}
          {startError && !review ? (
            <p role="alert" className="text-failure mt-3 text-base">
              {startError}
            </p>
          ) : null}
        </div>
      ) : null}
      {activeRun ? (
        <div className="px-4 pb-4 sm:px-5">
          <RunProgress detail={activeRun} />
        </div>
      ) : null}
    </div>
  );
}
