import Link from "next/link";
import { RECORD_STATE, type RecordState } from "@/lib/agent-view";
import {
  AMAZON_TRACE_ID,
  RERUN_TRACE_ID,
  type LiveLookup,
  type StoredCounts,
} from "@/lib/agent-data";

// The border carries the meaning and nothing else may change it: solid says
// something about the platform now, dashed says nothing about it.
const STYLE: Record<
  RecordState,
  { border: string; tone: string; mark: string; solid: boolean }
> = {
  live: {
    border: "border-signal/40",
    tone: "var(--signal)",
    mark: "text-signal",
    solid: true,
  },
  fixture: {
    border: "border-disagreement/50 border-dashed",
    tone: "var(--disagreement)",
    mark: "text-disagreement",
    solid: false,
  },
  historical: {
    border: "border-border-strong border-dashed",
    tone: "var(--text-secondary)",
    mark: "text-text-secondary",
    solid: false,
  },
  unavailable: {
    border: "border-failure/50 border-dashed",
    tone: "var(--failure)",
    mark: "text-failure",
    solid: false,
  },
};

const LINK =
  "text-accent hover:text-text-primary inline-flex min-h-11 items-center gap-1.5 text-base underline underline-offset-4 sm:text-sm";

/** A short form of a trace id, with the whole id on hover. */
function ShortId({ id }: { id: string }) {
  return (
    <p className="text-text-tertiary font-mono text-sm" title={id}>
      Trace {id.slice(0, 8)}
    </p>
  );
}

/**
 * One kind of record. The head says what the kind is, the body is the one real instance of it
 * and the foot is the single action. Every card has the same three parts at the same weight,
 * so the four read as one set. Hover or focus brings a card forward, draws a rail in its tone
 * and lets its siblings recede. The border style is never touched by any of that.
 */
function Card({
  state,
  fact,
  support,
  id,
  foot,
  lookup,
}: {
  state: RecordState;
  fact: string;
  support: string;
  id?: string | null;
  foot: React.ReactNode;
  lookup?: LiveLookup;
}) {
  const s = STYLE[state];
  return (
    <li
      data-record-state={state}
      style={{ ["--tone" as string]: s.tone }}
      className={`instrument rec bg-background-elevated/60 flex flex-col rounded-xl border p-5 ${s.border}`}
    >
      <span aria-hidden="true" className="rec-rail" />
      <div className="flex items-start justify-between gap-3">
        <h3 className={`text-lg font-semibold tracking-tight ${s.mark}`}>
          {RECORD_STATE[state].label}
        </h3>
        <svg
          aria-hidden="true"
          viewBox="0 0 16 16"
          className={`mt-1.5 h-4 w-4 shrink-0 ${s.mark}`}
        >
          {s.solid ? (
            <circle cx="8" cy="8" r="6" fill="currentColor" />
          ) : (
            <circle
              cx="8"
              cy="8"
              r="6"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.5"
              strokeDasharray="2.4 2.2"
            />
          )}
        </svg>
      </div>
      <p className="text-text-tertiary mt-0.5 text-sm">
        {s.solid
          ? "Says something about the platform"
          : "Says nothing about the platform now"}
      </p>
      <p className="text-text-secondary mt-3 text-base leading-relaxed text-pretty">
        {RECORD_STATE[state].meaning}
      </p>
      <div className="border-border mt-4 flex flex-1 flex-col gap-1 border-t pt-4">
        <p
          className="text-text-primary text-base leading-snug font-medium"
          data-lookup={lookup}
        >
          {fact}
        </p>
        <p className="text-text-secondary text-base leading-relaxed">
          {support}
        </p>
        {id ? <ShortId id={id} /> : null}
        <div className="mt-auto pt-2">{foot}</div>
      </div>
    </li>
  );
}

function Go({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <Link href={href} className={`${LINK} rec-link`}>
      {children}
      <span aria-hidden="true" className="rec-go">
        →
      </span>
    </Link>
  );
}

/** What the live lookup of the original Amazon trace returned, in words. */
function lookupText(lookup: LiveLookup): { fact: string; support: string } {
  if (lookup === "available") {
    return {
      fact: "The original Amazon record is available.",
      support:
        "A live lookup found it, so it is no longer unavailable. Investigations opens it.",
    };
  }
  if (lookup === "unavailable") {
    return {
      fact: "The original Amazon record cannot be retrieved.",
      support:
        "A live lookup just now found no trace under its id. It aged out of the event log.",
    };
  }
  return {
    fact: "The lookup could not be made.",
    support:
      "The gateway did not answer, so whether the record exists is not known.",
  };
}

/** The stored count for a live or fixture card, or the honest reason there is none. */
function counted(
  counts: StoredCounts | null,
  key: "live" | "fixture",
  support: string,
): { fact: string; support: string } {
  if (counts === null) {
    return {
      fact: "Count not known",
      support:
        "The stored investigations could not be read, so nothing is shown in their place.",
    };
  }
  const n = counts[key];
  if (n === 0) return { fact: "None stored", support: "Nothing to open yet." };
  return { fact: `${n} stored${n === 50 ? " (newest 50 read)" : ""}`, support };
}

/**
 * The four kinds of record the Agent pages can show, each with what it means and one real
 * instance: how many stored investigations are live or fixture (counted from the listing),
 * the preserved Amazon disagreement capture, and a live lookup of that same execution. The
 * lookup decides whether the last card says "available", "unavailable" or "unknown", so a
 * record that aged out reads as a stated fact and never as a broken page.
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
  const live = counted(
    counts,
    "live",
    "Counted from the stored investigation listing, newest first.",
  );
  const fixture = counted(
    counts,
    "fixture",
    "Counted from the same listing. Fixtures are never mixed into the live count.",
  );
  const gone = lookupText(lookup);
  const newestLive = counts?.newestLive ?? null;
  const newestFixture = counts?.newestFixture ?? null;
  return (
    <ul className="rec-list grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <Card
        state="live"
        {...live}
        id={newestLive}
        foot={
          newestLive ? (
            <Go href={`/agent/${newestLive}`}>Open the newest</Go>
          ) : null
        }
      />
      <Card
        state="fixture"
        {...fixture}
        id={newestFixture}
        foot={
          newestFixture ? (
            <Go href={`/agent/${newestFixture}`}>Open the newest</Go>
          ) : null
        }
      />
      <Card
        state="historical"
        fact="Amazon judge disagreement"
        support="The flash judge scored it 1.000 and the frontier judge scored it 0.000."
        id={AMAZON_TRACE_ID}
        foot={<Go href="/#evidence-heading">See the capture</Go>}
      />
      <Card
        state="unavailable"
        {...gone}
        lookup={lookup}
        id={AMAZON_TRACE_ID}
        foot={
          lookup === "unavailable" && rerun === "available" ? (
            <div data-rerun="available">
              <p className="text-text-secondary text-base leading-relaxed">
                Asked again, the same question is a separate trace without a
                frontier score.
              </p>
              <Go href={`/investigations?trace=${RERUN_TRACE_ID}`}>
                Open the Amazon trace
              </Go>
            </div>
          ) : null
        }
      />
    </ul>
  );
}
