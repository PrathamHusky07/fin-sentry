import Link from "next/link";
import type { RequestFlow as RequestFlowData } from "@/lib/overview-data";

interface Segment {
  key: string;
  label: string;
  count: number;
  fill: string;
  href: string;
}

interface Placed extends Segment {
  x: number;
  w: number;
  level: number;
  /** x of the leader line that joins the bar to its label. */
  leaderX: number;
  /** True when the label would run past the bar, so it is right-aligned. */
  flip: boolean;
}

const BAR_W = 1000;
const GAP = 2;
const MIN_W = 4;
const CHAR_W = 7.4;

/** Proportional widths with a visible minimum, normalized to the bar. Each
 * segment gets a label under the bar, joined by a leader line. Labels that
 * would run off the right edge flip to end at their leader, and labels are
 * stacked into levels so neighbors never overlap. */
function place(segments: Segment[]): Placed[] {
  const total = segments.reduce((sum, s) => sum + s.count, 0);
  const visible = segments.filter((s) => s.count > 0);
  const room = BAR_W - GAP * Math.max(0, visible.length - 1);
  const natural = visible.map((s) => Math.max(MIN_W, (s.count / total) * room));
  const over = natural.reduce((a, b) => a + b, 0) - room;
  const big = natural.reduce((a, b) => Math.max(a, b), 0);
  const widths = natural.map((w) => (w === big ? w - over : w));
  const levels: [number, number][][] = [];
  let x = 0;
  return visible.map((s, i) => {
    const w = widths[i];
    const leaderX = x + Math.min(w / 2, 8);
    const labelW = (String(s.count).length + 1 + s.label.length) * CHAR_W;
    const flip = leaderX + 8 + labelW > BAR_W;
    const span: [number, number] = flip
      ? [leaderX - 8 - labelW, leaderX]
      : [leaderX, leaderX + 8 + labelW];
    let level = levels.findIndex((taken) =>
      taken.every(([from, to]) => span[1] + 10 < from || span[0] - 10 > to),
    );
    if (level === -1) level = levels.push([]) - 1;
    levels[level].push(span);
    const placed = { ...s, x, w, level, leaderX, flip };
    x += w + GAP;
    return placed;
  });
}

function Bar({ y, segments }: { y: number; segments: Placed[] }) {
  return (
    <g>
      {segments.map((s) => (
        <g key={s.key}>
          <rect x={s.x} y={y} width={s.w} height={34} rx={3} fill={s.fill} />
          <line
            x1={s.leaderX}
            x2={s.leaderX}
            y1={y + 34}
            y2={y + 46 + s.level * 26}
            stroke="var(--border-strong)"
          />
          <text
            x={s.flip ? s.leaderX - 8 : s.leaderX + 8}
            y={y + 58 + s.level * 26}
            textAnchor={s.flip ? "end" : "start"}
            fontSize={13}
            className="fill-text-secondary"
          >
            <tspan
              fontSize={15}
              fontWeight={600}
              className="fill-text-primary tabular-metric"
            >
              {s.count}
            </tspan>{" "}
            {s.label}
          </text>
        </g>
      ))}
    </g>
  );
}

/**
 * The reliability pipeline as a two-stage flow. The top bar is every
 * persisted request split by where it ended, with the delivered part
 * highlighted. A ribbon carries the delivered part down to the second bar,
 * which splits those delivered answers by what the flash judge did with
 * them. Widths are counts over the stage total, so the shape is honest.
 */
export function RequestFlow({
  flow,
  frontierCount,
}: {
  flow: RequestFlowData;
  frontierCount: number;
}) {
  const outcomes = place([
    {
      key: "delivered",
      label: "Delivered",
      count: flow.delivered,
      fill: "var(--positive)",
      href: "/investigations?status=success",
    },
    {
      key: "output",
      label: "Stopped by output rails",
      count: flow.stoppedAt.output,
      fill: "var(--warning)",
      href: "/investigations?status=blocked",
    },
    {
      key: "retrieval",
      label: "Retrieval rail",
      count: flow.stoppedAt.retrieval,
      fill: "var(--warning)",
      href: "/investigations?status=blocked",
    },
    {
      key: "error",
      label: "Errored",
      count: flow.errored,
      fill: "var(--failure)",
      href: "/investigations?status=error",
    },
    {
      key: "input",
      label: "Input rails",
      count: flow.stoppedAt.input,
      fill: "var(--warning)",
      href: "/investigations?status=blocked",
    },
  ]);
  const verdicts = place([
    {
      key: "complete",
      label: "Complete verdict",
      count: flow.deliveredComplete,
      fill: "var(--positive)",
      href: "/investigations?judge_state=evaluated",
    },
    {
      key: "partial",
      label: "Partial",
      count: flow.deliveredPartial,
      fill: "var(--warning)",
      href: "/investigations?judge_state=partially_evaluated",
    },
    {
      key: "none",
      label: "No verdict",
      count: flow.deliveredUnjudged,
      fill: "var(--text-tertiary)",
      href: "/investigations?judge_state=never_evaluated",
    },
    {
      key: "judge-error",
      label: "Judge error",
      count: flow.deliveredJudgeFailed,
      fill: "var(--accent)",
      href: "/investigations?judge_state=judge_failed",
    },
  ]);
  const delivered = outcomes.find((s) => s.key === "delivered");
  const outcomeLevels = Math.max(0, ...outcomes.map((s) => s.level)) + 1;
  const topBarY = 30;
  const bottomBarY = topBarY + 46 + outcomeLevels * 26 + 44;
  const verdictLevels = Math.max(0, ...verdicts.map((s) => s.level)) + 1;
  const height = bottomBarY + 46 + verdictLevels * 26 + 10;

  const links = [...outcomes, ...verdicts];

  return (
    <section aria-labelledby="flow-heading">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2
          id="flow-heading"
          className="text-text-primary text-2xl font-semibold tracking-tight"
        >
          Reliability pipeline
        </h2>
        <p className="text-text-tertiary text-sm">
          {flow.total} persisted requests. Width is the count over the stage
          total.
        </p>
      </div>

      <div className="mt-8 hidden lg:block">
        <svg
          viewBox={`0 0 ${BAR_W} ${height}`}
          role="img"
          aria-label={`Of ${flow.total} requests, ${flow.delivered} were delivered. Of those, ${flow.deliveredComplete} have a complete flash verdict, ${flow.deliveredPartial} a partial one, ${flow.deliveredUnjudged} none and ${flow.deliveredJudgeFailed} a judge error.`}
          className="h-auto w-full"
        >
          <text x={0} y={16} fontSize={13} className="fill-text-tertiary">
            Every request, by where it ended
          </text>
          <Bar y={topBarY} segments={outcomes} />
          {delivered ? (
            <path
              d={`M${delivered.x},${topBarY + 34} L${delivered.x + delivered.w},${topBarY + 34} L${BAR_W},${bottomBarY} L0,${bottomBarY} Z`}
              fill="var(--positive)"
              opacity={0.1}
            />
          ) : null}
          <text
            x={0}
            y={bottomBarY - 10}
            fontSize={13}
            className="fill-text-tertiary"
          >
            The delivered answers, by what the flash judge did
          </text>
          <Bar y={bottomBarY} segments={verdicts} />
        </svg>
      </div>

      <ul className="border-border mt-6 grid border-t sm:grid-cols-2 lg:grid-cols-3">
        {links.map((s) => (
          <li key={s.key} className="border-border border-b">
            <Link
              href={s.href}
              className="hover:bg-surface/60 flex min-h-11 items-center justify-between gap-4 px-1 py-3 transition-colors sm:px-3"
            >
              <span className="flex items-center gap-2.5 text-base">
                <span
                  aria-hidden="true"
                  className="h-2.5 w-2.5 shrink-0 rounded-sm"
                  style={{ background: s.fill }}
                />
                <span className="text-text-secondary">{s.label}</span>
              </span>
              <span className="tabular-metric text-text-primary text-base">
                {s.count}
              </span>
            </Link>
          </li>
        ))}
      </ul>

      <p className="text-text-secondary mt-5 max-w-3xl text-base leading-relaxed">
        <span className="text-text-primary font-medium">
          {frontierCount} executions
        </span>{" "}
        were selected for frontier review. The sampler keeps about one trace in
        ten by trace id hash, so frontier review is a sample and not coverage.
      </p>
    </section>
  );
}
