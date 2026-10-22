"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import {
  ACTOR_LABEL,
  ACTOR_MEANING,
  LINKS,
  MAP,
  STAGES,
  linkState,
  nodeState,
  stageById,
  stagePosition,
  stepStage,
  type Actor,
  type MapLink,
  type Stage,
  type StageId,
} from "@/lib/agent-view";
import { useIsDesktop } from "@/lib/use-is-desktop";

const TONE: Record<Actor, string> = {
  request: "var(--text-secondary)",
  model: "var(--signal)",
  code: "var(--accent)",
};

const ACTOR_CHIP: Record<Actor, string> = {
  request: "text-text-secondary border-border-strong",
  model: "text-signal border-signal/40 bg-signal/10",
  code: "text-accent border-accent/40 bg-accent/10",
};

const INDEX = Object.fromEntries(STAGES.map((s, i) => [s.id, i])) as Record<
  StageId,
  number
>;

function nodePoint(id: StageId | "incident") {
  return id === "incident" ? MAP.incident : stagePosition(INDEX[id]);
}

/** The path of one connection. A spoke runs from the incident's edge to the foot of a stage,
 * a sequence link joins neighbouring stages, and the loop arcs over the stages between. */
function linkPath(link: MapLink): { d: string; arrow: string | null } {
  if (link.kind === "spoke") {
    const to = nodePoint(link.to as StageId);
    const from = MAP.incident;
    const dx = to.x - from.x;
    const dy = to.y + MAP.nodeH / 2 - from.y;
    const len = Math.hypot(dx, dy);
    const sx = from.x + (dx / len) * from.r;
    const sy = from.y + (dy / len) * from.r;
    return { d: `M${sx} ${sy} L${to.x} ${to.y + MAP.nodeH / 2}`, arrow: null };
  }
  if (link.kind === "sequence") {
    const a = nodePoint(link.from as StageId);
    const b = nodePoint(link.to as StageId);
    const x1 = a.x + MAP.nodeW / 2;
    const x2 = b.x - MAP.nodeW / 2;
    return {
      d: `M${x1} ${a.y} L${x2} ${b.y}`,
      arrow: `${x2},${b.y} ${x2 - 8},${b.y - 4.5} ${x2 - 8},${b.y + 4.5}`,
    };
  }
  const a = nodePoint(link.from as StageId);
  const b = nodePoint(link.to as StageId);
  const top = MAP.nodeH / 2;
  const lift = 96;
  return {
    d: `M${a.x} ${a.y - top} C${a.x} ${a.y - top - lift} ${b.x} ${b.y - top - lift} ${b.x} ${b.y - top - 8}`,
    arrow: `${b.x},${b.y - top} ${b.x - 4.5},${b.y - top - 9} ${b.x + 4.5},${b.y - top - 9}`,
  };
}

function StagePanel({
  stage,
  previewing = false,
}: {
  stage: Stage;
  /** True while the pointer or keyboard focus is on a stage that is not the selected one. */
  previewing?: boolean;
}) {
  const index = INDEX[stage.id];
  return (
    <div
      id="agent-step-detail"
      role="region"
      // A preview follows the pointer, so announcing each one would talk over the person.
      // Focus already speaks the stage's own label, and a committed selection is announced.
      aria-live={previewing ? "off" : "polite"}
      aria-label={`Stage ${index + 1}: ${stage.title}`}
      style={{ ["--tone" as string]: TONE[stage.actor] }}
      className="instrument border-line bg-background-elevated/70 swap-in grid gap-6 rounded-xl p-5 sm:p-6 lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)] lg:gap-10"
      key={stage.id}
    >
      <div>
        <div className="flex flex-wrap items-center gap-3">
          <p className="eyebrow">
            Stage {index + 1} of {STAGES.length}
          </p>
          <span
            className={`rounded-md border px-1.5 py-0.5 text-xs font-medium ${ACTOR_CHIP[stage.actor]}`}
          >
            {ACTOR_LABEL[stage.actor]}
          </span>
          {previewing ? (
            <span className="text-text-tertiary text-sm">
              Preview. Click or press Enter to keep this stage.
            </span>
          ) : null}
        </div>
        <h3 className="text-text-primary mt-2 text-2xl font-semibold tracking-tight">
          {stage.title}
        </h3>
        <p className="text-text-secondary mt-3 max-w-prose text-base leading-relaxed text-pretty">
          {stage.detail}
        </p>
        <p className="text-text-tertiary mt-3 text-base sm:text-sm">
          {ACTOR_MEANING[stage.actor]}
        </p>
      </div>
      <dl className="border-border space-y-5 lg:border-l lg:pl-8">
        <div>
          <dt className="eyebrow">Where the investigation can stop</dt>
          <dd className="text-text-primary mt-1.5 text-base leading-relaxed text-pretty">
            {stage.stops ??
              "No exit starts here. The earlier stages hold the stops, and this one reports what they left."}
          </dd>
        </div>
        <div>
          <dt className="eyebrow">In a stored case file</dt>
          <dd className="text-text-secondary mt-1.5 text-base leading-relaxed text-pretty">
            {stage.inCaseFile}
          </dd>
        </div>
      </dl>
    </div>
  );
}

function Legend() {
  return (
    <ul className="flex flex-wrap gap-x-5 gap-y-1.5">
      {(Object.keys(ACTOR_LABEL) as Actor[]).map((actor) => (
        <li
          key={actor}
          className="text-text-secondary flex items-center gap-2 text-base sm:text-sm"
        >
          <span
            aria-hidden="true"
            className="h-2.5 w-2.5 rounded-sm"
            style={{ background: TONE[actor] }}
          />
          <span className="text-text-primary">{ACTOR_LABEL[actor]}</span>
        </li>
      ))}
    </ul>
  );
}

/** The wide drawing: the incident in the middle below an arc of six stages, a spoke from the
 * incident to each, the sequence along the arc and the one loop back to Plan. */
function MapDrawing({
  selected,
  preview,
  onSelect,
  onPreview,
}: {
  selected: StageId;
  preview: StageId | null;
  onSelect: (id: StageId) => void;
  onPreview: (id: StageId | null) => void;
}) {
  const [keyboard, setKeyboard] = useState<StageId | null>(null);
  const refs = useRef(new Map<StageId, SVGGElement>());
  const active = preview ?? selected;
  const { incident } = MAP;

  return (
    <svg
      viewBox={`0 0 ${MAP.width} ${MAP.height}`}
      role="group"
      aria-label="Investigation map. How one investigation runs, from a trigger to a conclusion or an abstention. It shows the mechanism and is not a record of any one run."
      className="im h-auto w-full overflow-visible"
      style={{ ["--im-tone" as string]: TONE[stageById(active).actor] }}
    >
      <defs>
        <linearGradient id="im-face" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" style={{ stopColor: "var(--surface-high)" }} />
          <stop offset="1" style={{ stopColor: "var(--surface)" }} />
        </linearGradient>
        <radialGradient id="im-wash">
          <stop
            offset="0"
            style={{ stopColor: "var(--im-tone)", stopOpacity: 0.12 }}
          />
          <stop
            offset="1"
            style={{ stopColor: "var(--im-tone)", stopOpacity: 0 }}
          />
        </radialGradient>
      </defs>
      <ellipse
        aria-hidden="true"
        cx={MAP.width / 2}
        cy={250}
        rx={480}
        ry={190}
        fill="url(#im-wash)"
        pointerEvents="none"
      />
      {LINKS.map((link) => {
        const { d, arrow } = linkPath(link);
        const state = linkState(link, active);
        const tone =
          link.kind === "spoke" ? "var(--text-tertiary)" : "var(--accent)";
        return (
          <g
            key={link.id}
            className="cn-link"
            data-state={state}
            data-kind={link.kind === "spoke" ? "chord" : undefined}
          >
            <path
              d={d}
              fill="none"
              stroke={tone}
              strokeWidth={link.kind === "spoke" ? 1 : 1.6}
              strokeDasharray={link.kind === "loop" ? "5 5" : undefined}
              strokeLinecap="round"
            />
            {arrow ? <polygon points={arrow} fill={tone} /> : null}
          </g>
        );
      })}
      <text
        x={(nodePoint("plan").x + nodePoint("assess").x) / 2}
        y={
          Math.min(nodePoint("plan").y, nodePoint("assess").y) -
          MAP.nodeH / 2 -
          76
        }
        textAnchor="middle"
        className="fill-text-tertiary"
        fontSize={13}
      >
        Plans once more while budget remains
      </text>

      <g
        className="cn-inner"
        data-state={nodeState("incident", active)}
        style={{ cursor: "default" }}
      >
        <circle
          cx={incident.x}
          cy={incident.y}
          r={incident.r}
          fill="var(--surface)"
          stroke="var(--text-secondary)"
          strokeWidth={1.5}
        />
        <text
          x={incident.x}
          y={incident.y - 2}
          textAnchor="middle"
          className="fill-text-primary"
          fontSize={16}
          fontWeight={600}
        >
          Incident
        </text>
        <text
          x={incident.x}
          y={incident.y + 16}
          textAnchor="middle"
          className="fill-text-tertiary"
          fontSize={12}
        >
          scope and window
        </text>
      </g>

      {STAGES.map((stage, i) => {
        const { x, y } = stagePosition(i);
        const tone = TONE[stage.actor];
        const state = nodeState(stage.id, active);
        const w = MAP.nodeW;
        const h = MAP.nodeH;
        return (
          <g
            key={stage.id}
            ref={(el) => {
              if (el) refs.current.set(stage.id, el);
              else refs.current.delete(stage.id);
            }}
            className="cn-inner"
            data-state={state}
            data-keyboard={keyboard === stage.id}
            style={{ ["--tone" as string]: tone }}
            tabIndex={0}
            role="button"
            aria-label={`${i + 1}. ${stage.title}. ${ACTOR_LABEL[stage.actor]}. ${stage.short}`}
            aria-pressed={selected === stage.id}
            aria-controls="agent-step-detail"
            onClick={() => onSelect(stage.id)}
            onPointerEnter={(e) => {
              if (e.pointerType === "mouse") onPreview(stage.id);
            }}
            onPointerLeave={(e) => {
              if (e.pointerType === "mouse") onPreview(null);
            }}
            onFocus={(e) => {
              if (e.currentTarget.matches(":focus-visible")) {
                setKeyboard(stage.id);
                onPreview(stage.id);
              }
            }}
            onBlur={() => {
              setKeyboard(null);
              onPreview(null);
            }}
            onKeyDown={(e) => {
              if (e.key === "Enter" || e.key === " ") {
                e.preventDefault();
                onSelect(stage.id);
              } else if (e.key === "ArrowRight" || e.key === "ArrowDown") {
                e.preventDefault();
                refs.current.get(stepStage(stage.id, 1))?.focus();
              } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
                e.preventDefault();
                refs.current.get(stepStage(stage.id, -1))?.focus();
              }
            }}
          >
            <rect
              className="cn-halo"
              x={x - w / 2 - 8}
              y={y - h / 2 - 8}
              width={w + 16}
              height={h + 16}
              rx={22}
              fill={tone}
              fillOpacity={0.16}
            />
            <rect
              className="cn-focus-ring"
              x={x - w / 2 - 5}
              y={y - h / 2 - 5}
              width={w + 10}
              height={h + 10}
              rx={19}
              fill="none"
              stroke="var(--accent)"
              strokeWidth={2}
            />
            <rect
              className="im-body"
              x={x - w / 2}
              y={y - h / 2}
              width={w}
              height={h}
              rx={14}
              fill="url(#im-face)"
              stroke={tone}
              strokeOpacity={state === "rest" ? 0.55 : 0.95}
              strokeWidth={1.6}
            />
            <text
              x={x}
              y={y - 5}
              textAnchor="middle"
              className="fill-text-primary"
              fontSize={16}
              fontWeight={600}
            >
              {i + 1}. {stage.mapLabel}
            </text>
            <text
              x={x}
              y={y + 15}
              textAnchor="middle"
              fontSize={12.5}
              style={{ fill: tone }}
            >
              {ACTOR_LABEL[stage.actor]}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/** The narrow form: the same six stages as a vertical list under the incident, the selected
 * one expanding in place. */
function MapOutline({
  selected,
  onSelect,
}: {
  selected: StageId;
  onSelect: (id: StageId) => void;
}) {
  return (
    <div>
      <div className="border-border-strong bg-surface rounded-xl border px-4 py-3">
        <p className="text-text-primary text-base font-semibold">Incident</p>
        <p className="text-text-secondary text-base leading-snug">
          Every stage works on one incident, its scope and its time window.
        </p>
      </div>
      <ol className="border-border-strong mt-0 ml-4 border-l pt-3">
        {STAGES.map((stage, i) => {
          const open = selected === stage.id;
          return (
            <li key={stage.id} className="relative pb-3 pl-5 last:pb-0">
              <span
                aria-hidden="true"
                className="absolute top-6 -left-[5px] h-2.5 w-2.5 rounded-full border-2"
                style={{
                  borderColor: TONE[stage.actor],
                  background: open ? TONE[stage.actor] : "var(--background)",
                }}
              />
              <button
                type="button"
                aria-pressed={open}
                aria-expanded={open}
                aria-controls={open ? "agent-step-detail" : undefined}
                onClick={() => onSelect(stage.id)}
                className={`lift flex min-h-11 w-full flex-col items-start gap-1.5 rounded-xl border p-4 text-left ${
                  open
                    ? "border-line-active bg-surface-high"
                    : "border-line bg-background-elevated/70"
                }`}
              >
                <span className="flex w-full items-center justify-between gap-2">
                  <span className="text-text-primary text-lg font-semibold tracking-tight">
                    {i + 1}. {stage.title}
                  </span>
                  <span
                    className={`rounded-md border px-1.5 py-0.5 text-xs font-medium ${ACTOR_CHIP[stage.actor]}`}
                  >
                    {ACTOR_LABEL[stage.actor]}
                  </span>
                </span>
                <span className="text-text-secondary text-base leading-snug">
                  {stage.short}
                </span>
              </button>
              {open ? (
                <div className="mt-2">
                  <StagePanel stage={stage} />
                </div>
              ) : null}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

/**
 * The mechanism of one investigation as an interactive map: the incident, six connected
 * stages and the one loop back to planning. Selecting a stage brings it forward, lights its
 * real connections, quiets the rest and opens what the stage does and where an investigation
 * can stop. Hovering or focusing previews a stage and selecting commits it. The map explains
 * how the code runs. It draws no run, so it can never imply that a stage ran, that a
 * hypothesis held or that a cause was established.
 */
export function InvestigationMap() {
  const [selected, setSelected] = useState<StageId>("trigger");
  const [preview, setPreview] = useState<StageId | null>(null);
  const desktop = useIsDesktop();
  // The description follows the drawing: a hovered or focused stage shows at once and the
  // committed selection returns when the pointer or focus leaves. Narrow screens have no
  // hover, so the selected stage alone decides there.
  const shown = desktop && preview ? preview : selected;
  const stage = stageById(shown);

  return (
    <div>
      {desktop ? (
        <>
          <div className="mt-2">
            <MapDrawing
              selected={selected}
              preview={preview}
              onSelect={setSelected}
              onPreview={setPreview}
            />
          </div>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-x-8 gap-y-2">
            <Legend />
            <p className="text-text-tertiary text-sm">
              The mechanism, not a record of any one investigation.
            </p>
          </div>
          <div className="mt-5">
            <StagePanel stage={stage} previewing={shown !== selected} />
          </div>
        </>
      ) : (
        <>
          <MapOutline selected={selected} onSelect={setSelected} />
          <div className="mt-4 flex flex-col gap-2">
            <Legend />
            <p className="text-text-tertiary text-base">
              The mechanism, not a record of any one investigation.
            </p>
          </div>
        </>
      )}
      <p className="mt-4">
        <Link
          href="#investigations"
          className="text-accent hover:text-text-primary inline-flex min-h-11 items-center text-base underline underline-offset-4 sm:text-sm"
        >
          Read the stored investigations
        </Link>
      </p>
    </div>
  );
}
