"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AsyncState, type AsyncStatus } from "@/components/async-state";
import { CopyButton } from "@/components/copy-button";
import { ModeBadge, RedTeamOutcomeBadge } from "@/components/red-team-badges";
import { useDialogBehavior, useIsClient } from "@/components/trace-drilldown";
import { formatUtcSeconds, shortId } from "@/lib/format";
import {
  EVALUATOR_LABEL,
  OUTCOME_MEANING,
  evaluatorStatus,
  expectationLabel,
  expectedLabel,
  formatCost,
  formatDuration,
  layerLabel,
  sentGatewayRequest,
  traceHref,
  type ExecutionRecord,
} from "@/lib/red-team";
import { fetchExecution } from "@/lib/red-team-api";

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="border-border border-t pt-6">
      <h3 className="eyebrow">{title}</h3>
      <div className="mt-3 space-y-3">{children}</div>
    </section>
  );
}

function Row({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="grid gap-1 sm:grid-cols-[11rem_1fr] sm:gap-4">
      <dt className="text-text-tertiary text-sm">{label}</dt>
      <dd className="text-text-primary min-w-0 text-base break-words">
        {children}
      </dd>
    </div>
  );
}

function EvidenceValue({ value }: { value: unknown }) {
  if (value === null || typeof value !== "object") {
    return <span className="font-mono text-sm">{String(value)}</span>;
  }
  return (
    <pre className="bg-surface border-border thin-scroll max-h-56 overflow-auto rounded-md border p-3 font-mono text-xs leading-relaxed break-words whitespace-pre-wrap">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

function TraceProvenance({ e }: { e: ExecutionRecord }) {
  if (e.trace_ref) {
    return (
      <>
        <p className="text-text-secondary text-base leading-relaxed">
          This execution sent a request through the gateway, and the gateway
          stored a trace for it.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Link
            href={traceHref(e.trace_ref)}
            className="border-border-strong text-text-primary hover:bg-surface inline-flex min-h-11 items-center gap-2 rounded-lg border px-4 text-sm font-medium"
          >
            Open the trace in Investigations
            <span aria-hidden="true">→</span>
          </Link>
          <span className="text-text-tertiary font-mono text-xs break-all">
            {e.trace_ref}
          </span>
          <CopyButton value={e.trace_ref} label="Copy trace id" />
        </div>
      </>
    );
  }
  return (
    <p className="text-text-secondary text-base leading-relaxed">
      {sentGatewayRequest(e)
        ? "This execution sent a gateway request, but no stored trace was found within the lookup window. The result rests on the gateway response alone."
        : "This execution called the defense directly with a controlled input. It sent no gateway request, so no trace exists for it."}
    </p>
  );
}

function EvidenceBody({ e }: { e: ExecutionRecord }) {
  const entries = Object.entries(e.evidence);
  const evaluator = evaluatorStatus(e);
  return (
    <div className="space-y-8">
      <Section title="Expected against observed">
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="border-border rounded-lg border p-4">
            <p className="text-text-tertiary text-sm">
              Expected, stored with scenario version {e.scenario_version}
            </p>
            <p className="text-text-primary mt-1 text-base font-medium">
              {expectedLabel(e.expected)}
            </p>
            <p className="text-text-secondary mt-1 text-sm leading-relaxed">
              {e.expected.rationale}
            </p>
          </div>
          <div className="border-border rounded-lg border p-4">
            <p className="text-text-tertiary text-sm">
              Observed, from this execution
            </p>
            <p className="mt-1">
              <RedTeamOutcomeBadge outcome={e.outcome} state={e.state} />
            </p>
            <p className="text-text-secondary mt-2 text-sm leading-relaxed">
              {e.outcome ? OUTCOME_MEANING[e.outcome] : "Not finished yet."}
            </p>
          </div>
        </div>
        <p className="text-text-primary text-base">{expectationLabel(e)}.</p>
        {e.reason ? (
          <p className="text-text-secondary text-base leading-relaxed">
            {e.reason}
          </p>
        ) : null}
      </Section>

      <Section title="Which defense acted">
        <dl className="space-y-3">
          <Row label="Acting layer">
            {e.outcome === "caught"
              ? layerLabel(e.acting_layer)
              : "None credited"}
          </Row>
          {e.acting_check ? (
            <Row label="Check or reason">{e.acting_check}</Row>
          ) : null}
          <Row label="Evaluator">{EVALUATOR_LABEL[evaluator]}</Row>
        </dl>
      </Section>

      <Section title="Mode">
        <div className="flex flex-wrap items-center gap-2">
          <ModeBadge mode={e.mode} />
        </div>
        {e.mode === "deterministic" ? (
          <p className="text-text-secondary text-base leading-relaxed">
            This was a deterministic execution. It exercised the real defense
            with a controlled input and made no billable model calls. It is not
            a measurement of live model behavior.
          </p>
        ) : (
          <p className="text-text-secondary text-base leading-relaxed">
            This was a judge-assisted execution. Detection depended on the
            Gemini faithfulness judge. It made {e.gemini_calls} Gemini{" "}
            {e.gemini_calls === 1 ? "call" : "calls"} at a recorded cost of{" "}
            {formatCost(e.cost_usd)}.
          </p>
        )}
      </Section>

      <Section title="Trace">
        <TraceProvenance e={e} />
      </Section>

      <Section title="Evidence recorded">
        {entries.length === 0 ? (
          <p className="text-text-secondary text-base">
            No evidence was recorded. The harness stopped before it measured
            anything.
          </p>
        ) : (
          <dl className="space-y-3">
            {entries.map(([key, value]) => (
              <Row key={key} label={key}>
                <EvidenceValue value={value} />
              </Row>
            ))}
          </dl>
        )}
      </Section>

      <Section title="Record">
        <dl className="space-y-3">
          <Row label="Execution">
            <span className="font-mono text-sm break-all">
              {e.execution_id}
            </span>
          </Row>
          <Row label="Run">
            <span className="font-mono text-sm">{shortId(e.run_id)}</span>
          </Row>
          <Row label="Started">
            {e.started_at
              ? `${formatUtcSeconds(e.started_at)} UTC`
              : "Not started"}
          </Row>
          <Row label="Duration">{formatDuration(e.duration_ms)}</Row>
        </dl>
      </Section>
    </div>
  );
}

/** The evidence drawer for one stored execution, loaded by id so a shared
 * link opens the same record. Focus is trapped and Escape closes it. */
export function RedTeamEvidence({
  executionId,
  onClose,
}: {
  executionId: string;
  onClose: () => void;
}) {
  const [record, setRecord] = useState<ExecutionRecord | null>(null);
  const [status, setStatus] = useState<AsyncStatus>("loading");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [retryToken, setRetryToken] = useState(0);
  const dialogRef = useRef<HTMLDivElement>(null);
  const isClient = useIsClient();
  useDialogBehavior(dialogRef, onClose, isClient);

  useEffect(() => {
    let cancelled = false;
    fetchExecution(executionId)
      .then((row) => {
        if (!cancelled) {
          setRecord(row);
          setStatus("ready");
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setErrorMessage(
            err instanceof Error ? err.message : "Execution unreachable.",
          );
          setStatus("error");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [executionId, retryToken]);

  if (!isClient) return null;
  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Execution evidence"
      className="swap-in fixed inset-0 z-50 flex justify-end overscroll-contain bg-black/60 backdrop-blur-sm"
      onClick={onClose}
    >
      <div
        ref={dialogRef}
        tabIndex={-1}
        className="modal-in border-line-active bg-background-elevated flex h-full w-full max-w-3xl origin-right flex-col border-l shadow-[-30px_0_60px_-30px_rgb(0_0_0/0.8)] outline-none"
        onClick={(ev) => ev.stopPropagation()}
      >
        <header className="border-border bg-background-elevated/95 sticky top-0 z-10 border-b px-5 pt-4 pb-4 backdrop-blur sm:px-8">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-text-tertiary text-sm">Execution</p>
              <p className="text-text-primary text-lg font-semibold">
                {record
                  ? `${record.scenario_id}, version ${record.scenario_version}`
                  : "Loading"}
              </p>
            </div>
            <button
              type="button"
              onClick={onClose}
              className="border-border-strong text-text-primary hover:bg-surface inline-flex min-h-11 shrink-0 items-center gap-2 rounded-lg border px-3 text-sm font-medium"
            >
              Close
              <kbd className="text-text-tertiary hidden font-mono text-xs sm:inline">
                Esc
              </kbd>
            </button>
          </div>
          {record ? (
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <RedTeamOutcomeBadge
                outcome={record.outcome}
                state={record.state}
                withMeaning
              />
              <ModeBadge mode={record.mode} />
            </div>
          ) : null}
        </header>
        <div className="thin-scroll flex-1 overflow-y-auto overscroll-contain px-5 py-8 sm:px-8">
          <AsyncState
            status={status}
            errorMessage={errorMessage}
            onRetry={() => {
              setStatus("loading");
              setRetryToken((n) => n + 1);
            }}
            loadingLabel="Loading execution evidence"
          >
            {record ? <EvidenceBody e={record} /> : null}
          </AsyncState>
        </div>
      </div>
    </div>,
    document.body,
  );
}
