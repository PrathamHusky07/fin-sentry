import Link from "next/link";
import { RECORD_STATE, type RecordState } from "@/lib/agent-view";
import {
  AMAZON_TRACE_ID,
  RERUN_TRACE_ID,
  type LiveLookup,
  type StoredCounts,
} from "@/lib/agent-data";

const STYLE: Record<
  RecordState,
  { border: string; tone: string; mark: string }
> = {
  live: {
    border: "border-signal/40",
    tone: "var(--signal)",
    mark: "text-signal",
  },
  fixture: {
    border: "border-disagreement/50 border-dashed",
    tone: "var(--disagreement)",
    mark: "text-disagreement",
  },
  historical: {
    border: "border-border-strong border-dashed",
    tone: "var(--text-secondary)",
    mark: "text-text-secondary",
  },
  unavailable: {
    border: "border-failure/50 border-dashed",
    tone: "var(--failure)",
    mark: "text-failure",
  },
};

function Card({
  state,
  children,
}: {
  state: RecordState;
  children: React.ReactNode;
}) {
  const s = STYLE[state];
  return (
    <li
      data-record-state={state}
      style={{ ["--tone" as string]: s.tone }}
      className={`instrument bg-background-elevated/60 flex flex-col rounded-xl border p-5 ${s.border}`}
    >
      <h3 className={`text-lg font-semibold tracking-tight ${s.mark}`}>
        {RECORD_STATE[state].label}
      </h3>
      <p className="text-text-secondary mt-2 text-base leading-relaxed text-pretty">
        {RECORD_STATE[state].meaning}
      </p>
      <div className="border-border mt-4 border-t pt-4">{children}</div>
    </li>
  );
}

const LINK =
  "text-accent hover:text-text-primary inline-flex min-h-11 items-center text-base underline underline-offset-4 sm:text-sm";

/** What the live lookup of the Amazon trace returned, in words, for the unavailable card. */
function lookupText(lookup: LiveLookup): { head: string; body: string } {
  if (lookup === "available") {
    return {
      head: "The Amazon record is available.",
      body: "A live lookup of the execution found it, so it is no longer unavailable. The Investigations page opens it.",
    };
  }
  if (lookup === "unavailable") {
    return {
      head: "The Amazon record cannot be retrieved.",
      body: "A live lookup just now found no trace stored under its id. The event log expired that execution under its earlier seven-day retention. The preserved capture is all that remains of it.",
    };
  }
  return {
    head: "The lookup could not be made.",
    body: "The gateway did not answer, so whether the Amazon record exists is not known. Nothing is shown in its place.",
  };
}

/**
 * The four kinds of record the Agent pages can show, each with what it means and one real
 * instance: how many stored investigations are live or fixture (counted from the listing),
 * the preserved Amazon disagreement capture, and a live lookup of that same execution. The
 * lookup decides whether the last card says "available", "unavailable" or "unknown", so an
 * expired record reads as a stated fact and never as a broken page.
 */
export function RecordStates({
  counts,
  lookup,
  rerun,
}: {
  counts: StoredCounts | null;
  lookup: LiveLookup;
  /** A live lookup of the trace made when the same question was asked again. */
  rerun: LiveLookup;
}) {
  const gone = lookupText(lookup);
  return (
    <ul className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <Card state="live">
        {counts === null ? (
          <p className="text-text-secondary text-base">
            The stored investigations could not be read, so the count is not
            known.
          </p>
        ) : counts.live === 0 ? (
          <p className="text-text-secondary text-base">
            None stored. A live execution appears here after one is started.
          </p>
        ) : (
          <>
            <p className="text-text-primary text-base">
              {counts.live} stored
              {counts.live === 50 ? " (newest 50 read)" : ""}
            </p>
            {counts.newestLive ? (
              <Link href={`/agent/${counts.newestLive}`} className={LINK}>
                Open the newest
              </Link>
            ) : null}
          </>
        )}
      </Card>
      <Card state="fixture">
        {counts === null ? (
          <p className="text-text-secondary text-base">
            The stored investigations could not be read, so the count is not
            known.
          </p>
        ) : counts.fixture === 0 ? (
          <p className="text-text-secondary text-base">None stored.</p>
        ) : (
          <>
            <p className="text-text-primary text-base">
              {counts.fixture} stored
              {counts.fixture === 50 ? " (newest 50 read)" : ""}
            </p>
            {counts.newestFixture ? (
              <Link href={`/agent/${counts.newestFixture}`} className={LINK}>
                Open the newest
              </Link>
            ) : null}
          </>
        )}
      </Card>
      <Card state="historical">
        <p className="text-text-primary text-base leading-snug">
          Amazon judge disagreement. Stored 2026-10-03, captured 2026-10-08.
        </p>
        <p className="text-text-secondary mt-1 text-base">
          The flash judge scored it 1.000 and the frontier judge scored it
          0.000.
        </p>
        <Link href="/#evidence-heading" className={LINK}>
          See the capture
        </Link>
      </Card>
      <Card state="unavailable">
        <p
          className="text-text-primary text-base leading-snug font-medium"
          data-lookup={lookup}
        >
          {gone.head}
        </p>
        <p className="text-text-secondary mt-1 text-base leading-relaxed">
          {gone.body}
        </p>
        <p className="text-text-tertiary mt-2 font-mono text-sm break-all">
          {AMAZON_TRACE_ID}
        </p>
        {lookup === "unavailable" && rerun === "available" ? (
          <p
            className="text-text-secondary mt-3 text-base leading-relaxed"
            data-rerun="available"
          >
            The same question was asked again and is stored as a different
            trace. It is not the original and shows no disagreement, because the
            frontier judge was not sampled for it.{" "}
            <Link
              href={`/investigations?trace=${RERUN_TRACE_ID}`}
              className={LINK}
            >
              Open the new trace
            </Link>
          </p>
        ) : null}
      </Card>
    </ul>
  );
}
