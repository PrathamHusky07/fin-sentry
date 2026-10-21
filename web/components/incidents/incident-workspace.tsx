"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AsyncState, type AsyncStatus } from "@/components/async-state";
import { EvidenceExplorer } from "@/components/incidents/evidence-explorer";
import { ExecutionTimeline } from "@/components/incidents/execution-timeline";
import { HypothesisLedger } from "@/components/incidents/hypothesis-ledger";
import { IncidentHeader } from "@/components/incidents/incident-header";
import { IncidentVerdict } from "@/components/incidents/incident-verdict";
import { NotEstablished } from "@/components/incidents/not-established";
import { SectionRail } from "@/components/incidents/section-rail";
import { SpendPanel } from "@/components/incidents/spend-panel";
import type { Detail } from "@/lib/incidents";
import { IncidentApiError, fetchIncident } from "@/lib/incidents-api";

const POLL_MS = 2000;

const SECTIONS = [
  { id: "outcome", label: "Outcome" },
  { id: "hypotheses", label: "Hypotheses" },
  { id: "timeline", label: "Timeline" },
  { id: "evidence", label: "Evidence" },
  { id: "gaps", label: "Not established" },
  { id: "budget", label: "Budget" },
];

/**
 * One stored investigation, opened by its id. Everything is read from the stored session
 * through /ops/investigations/{id}. Opening or refreshing this page never starts an
 * investigation or calls a model. A session that is still running is re-read every two
 * seconds as plain REST reads of stored rows, which is not a live feed, and the polling
 * stops when the session ends.
 */
export function IncidentWorkspace({ id }: { id: string }) {
  const [detail, setDetail] = useState<Detail | null>(null);
  const [status, setStatus] = useState<AsyncStatus>("loading");
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    async function load() {
      try {
        const next = await fetchIncident(id);
        if (cancelled) return;
        setDetail(next);
        setStatus("ready");
        if (next.status === "running") timer = setTimeout(load, POLL_MS);
      } catch (err: unknown) {
        if (cancelled) return;
        if (err instanceof IncidentApiError && err.status === 404) {
          setNotFound(true);
          setStatus("ready");
          return;
        }
        setError(
          err instanceof Error
            ? err.message
            : "The gateway could not be reached.",
        );
        setStatus("error");
      }
    }
    void load();
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
    };
  }, [id, retry]);

  return (
    <div className="ctx ctx-forensic mobile-readable flex-1">
      {detail ? <SectionRail sections={SECTIONS} /> : null}
      <div className="mx-auto w-full max-w-7xl px-4 py-10 sm:px-8 sm:py-14">
        <AsyncState
          status={status}
          errorMessage={error}
          onRetry={() => {
            setStatus("loading");
            setRetry((n) => n + 1);
          }}
          loadingLabel="Loading the stored investigation"
        >
          {notFound || !detail ? (
            <div className="border-border-strong rounded-xl border border-dashed px-6 py-14 text-center">
              <p className="text-text-primary text-lg font-medium">
                No investigation is stored under this id.
              </p>
              <Link
                href="/agent"
                className="text-accent mt-4 inline-flex min-h-11 items-center underline underline-offset-4"
              >
                See all investigations
              </Link>
            </div>
          ) : (
            <div className="space-y-14">
              <IncidentHeader detail={detail} />
              <div id="outcome" className="scroll-mt-32">
                <IncidentVerdict detail={detail} />
              </div>
              <HypothesisLedger detail={detail} />
              <ExecutionTimeline detail={detail} />
              <EvidenceExplorer detail={detail} />
              <NotEstablished detail={detail} />
              <SpendPanel detail={detail} />
            </div>
          )}
        </AsyncState>
      </div>
    </div>
  );
}
