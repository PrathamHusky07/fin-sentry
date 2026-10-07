import type { ReactNode } from "react";
import { formatUtc } from "@/lib/format";
import type { MetricsSnapshot } from "@/lib/metrics-snapshot";

// These readouts only render once a snapshot has arrived in the browser, so
// the viewer’s own locale is safe to use (no server-rendered text to match).
const NUMBER = new Intl.NumberFormat(undefined);

function count(n: number | null | undefined): string | null {
  return n === null || n === undefined ? null : NUMBER.format(n);
}

function score(n: number | null | undefined): string | null {
  return n === null || n === undefined ? null : n.toFixed(3);
}

function words(key: string): string {
  const spaced = key.replace(/_/g, " ");
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

function scopeLine(
  windowEnd: string | null | undefined,
  prefix = "Latest one-minute bucket",
): string {
  return windowEnd
    ? `${prefix}, ended ${formatUtc(windowEnd)}`
    : `${prefix}, none reported`;
}

function Row({
  label,
  value,
  unit,
  note,
  stale,
}: {
  label: string;
  value: string | null;
  unit?: string;
  note?: string;
  stale: boolean | null;
}) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-4">
        <dt className="text-text-secondary text-sm">{label}</dt>
        <dd
          className={`tabular-metric text-xl font-medium ${stale ? "text-text-secondary" : "text-text-primary"}`}
        >
          {value ?? "no data"}
          {value && unit ? (
            <span className="text-text-tertiary ml-1.5 text-sm font-normal">
              {unit}
            </span>
          ) : null}
        </dd>
      </div>
      {note ? (
        <p className="text-text-tertiary mt-1 text-sm leading-snug">{note}</p>
      ) : null}
    </div>
  );
}

function Group({
  title,
  scope,
  stale,
  children,
}: {
  title: string;
  scope: string;
  stale: boolean | null;
  children: ReactNode;
}) {
  return (
    <section
      aria-label={title}
      className="border-line bg-background-elevated/70 hover:border-line-hover rounded-xl border p-5 transition-colors duration-[var(--dur-base)]"
    >
      <h3 className="text-text-primary text-base font-semibold">{title}</h3>
      <p className="text-text-tertiary mt-1 text-sm leading-snug">
        {scope}
        {stale ? (
          <span className="text-warning ml-2 font-medium">Stale</span>
        ) : null}
      </p>
      <dl className="mt-5 space-y-4">{children}</dl>
    </section>
  );
}

function Breakdown({
  counts,
  empty,
}: {
  counts: Record<string, number> | undefined;
  empty: string;
}) {
  const entries = Object.entries(counts ?? {}).sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) {
    return <p className="text-text-secondary text-sm">{empty}</p>;
  }
  return (
    <dl className="space-y-1.5">
      {entries.map(([key, value]) => (
        <div key={key} className="flex items-baseline justify-between gap-4">
          <dt className="text-text-secondary text-sm">{words(key)}</dt>
          <dd className="tabular-metric text-text-primary text-base">
            {NUMBER.format(value)}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * Evaluation telemetry: what the judges did, from the same snapshot that
 * feeds the request readouts. Every group names its window. The flash and
 * usage groups read one one-minute bucket each, and the frontier group sums
 * the last fifteen minutes. Nothing here is a trend, and a stale group says
 * so in words.
 */
export function EvalTelemetry({
  snapshot,
}: {
  snapshot: MetricsSnapshot | null;
}) {
  const faith = snapshot?.faithfulness ?? null;
  const rel = snapshot?.relevance ?? null;
  const tokens = snapshot?.tokens ?? null;
  const cost = snapshot?.cost ?? null;
  const frontier = snapshot?.frontier ?? null;

  const tokenTotal =
    tokens &&
    tokens.input_tokens_total !== null &&
    tokens.output_tokens_total !== null
      ? tokens.input_tokens_total +
        tokens.output_tokens_total +
        (tokens.thoughts_tokens_total ?? 0)
      : null;

  const frontierTotal = frontier
    ? Object.values(frontier.verdict_counts).reduce((a, b) => a + b, 0)
    : null;

  return (
    <section aria-labelledby="eval-heading">
      <h2
        id="eval-heading"
        className="text-text-primary text-2xl font-semibold tracking-tight"
      >
        Evaluation telemetry
      </h2>
      <p className="text-text-secondary mt-2 max-w-2xl text-base leading-relaxed">
        What the judges did most recently. Each group names its window, and a
        group with nothing in its window says so.
      </p>

      <div className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <Group
          title="Flash judge, faithfulness"
          scope={scopeLine(faith?.window_end)}
          stale={faith?.stale ?? null}
        >
          <Row
            label="Verdicts"
            value={count(faith?.verdicts_count)}
            stale={faith?.stale ?? null}
          />
          <Row
            label="Average faithfulness"
            value={score(faith?.avg_faithfulness)}
            stale={faith?.stale ?? null}
          />
          <Row
            label="Complete"
            value={count(faith?.complete_count)}
            stale={faith?.stale ?? null}
          />
          <Row
            label="Skipped"
            value={count(faith?.skipped_count)}
            note="Metrics the judge skipped, for example after a timeout."
            stale={faith?.stale ?? null}
          />
        </Group>

        <Group
          title="Flash judge, relevance"
          scope={scopeLine(rel?.window_end)}
          stale={rel?.stale ?? null}
        >
          <Row
            label="Verdicts"
            value={count(rel?.verdicts_count)}
            stale={rel?.stale ?? null}
          />
          <Row
            label="Average answer relevance"
            value={score(rel?.avg_answer_relevance)}
            stale={rel?.stale ?? null}
          />
          <Row
            label="Average context relevance"
            value={score(rel?.avg_context_relevance)}
            stale={rel?.stale ?? null}
          />
        </Group>

        <Group
          title="Judge usage"
          scope={scopeLine(tokens?.window_end)}
          stale={tokens?.stale ?? null}
        >
          <Row
            label="Judge tokens"
            value={count(tokenTotal)}
            unit="tokens"
            note={`Flash judge only: Gemini input, output and thinking tokens in its latest one-minute bucket${tokens?.gemini_calls_total != null ? `, ${tokens.gemini_calls_total} calls` : ""}`}
            stale={tokens?.stale ?? null}
          />
          <Row
            label="Judge cost"
            value={
              cost?.cost_total_usd != null
                ? `$${cost.cost_total_usd.toFixed(6)}`
                : null
            }
            note="Flash judge only, estimated at Vertex AI standard pricing, in its latest one-minute bucket. Not platform spend."
            stale={cost?.stale ?? null}
          />
        </Group>

        <Group
          title={`Frontier tier, last ${frontier?.window_minutes ?? 15} minutes`}
          scope={
            frontier?.latest_window_end
              ? `Summed over the window, newest bucket ended ${formatUtc(frontier.latest_window_end)}`
              : "Summed over the window, no bucket in range"
          }
          stale={frontier?.stale ?? null}
        >
          <Row
            label="Verdicts"
            value={count(frontierTotal)}
            stale={frontier?.stale ?? null}
          />
          <div>
            <p className="text-text-tertiary mb-2 text-sm">By verdict</p>
            <Breakdown
              counts={frontier?.verdict_counts}
              empty="No frontier verdicts in this window."
            />
          </div>
          <div>
            <p className="text-text-tertiary mb-2 text-sm">
              Disagreement classes
            </p>
            <Breakdown
              counts={frontier?.disagreement_counts}
              empty="No disagreement classes in this window."
            />
          </div>
        </Group>
      </div>
    </section>
  );
}
