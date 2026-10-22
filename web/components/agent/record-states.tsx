import Link from "next/link";
import { RECORD_STATE, type RecordState } from "@/lib/agent-view";
import { AMAZON_TRACE_ID, type StoredCounts } from "@/lib/agent-data";

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
 * so the three read as one set. Hover or focus brings a card forward, draws a rail in its tone
 * and lets its siblings recede. The border style is never touched by any of that.
 */
function Card({
  state,
  fact,
  support,
  id,
  foot,
}: {
  state: RecordState;
  fact: string;
  support: string;
  id?: string | null;
  foot: React.ReactNode;
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
        <p className="text-text-primary text-base leading-snug font-medium">
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
 * The three kinds of record the Agent pages can show, each with what it means and one real
 * instance: how many stored investigations are live or fixture (counted from the listing) and
 * the preserved Amazon disagreement capture. A record that cannot be retrieved is not a kind of
 * record to browse, so it is stated where it happens, on the page for a case id nothing holds.
 */
export function RecordStates({ counts }: { counts: StoredCounts | null }) {
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
  const newestLive = counts?.newestLive ?? null;
  const newestFixture = counts?.newestFixture ?? null;
  return (
    <ul className="rec-list grid gap-4 lg:grid-cols-3">
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
    </ul>
  );
}
