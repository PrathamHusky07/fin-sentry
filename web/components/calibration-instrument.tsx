"use client";

import { useState, type CSSProperties } from "react";
import { formatUtc, relativeTime } from "@/lib/format";
import { CALIBRATION_POSITION_TONE } from "@/lib/labels";
import { useNow } from "@/lib/use-now";
import type {
  CalibrationHealthResponse,
  CalibrationPosition,
} from "@/lib/trace-api";

/** The visible slice of the kappa axis. Kappa runs from -1 to 1 in
 * principle. The thresholds all sit between 0.4 and 0.65, so the scale is
 * zoomed to where the decisions are, and says so. */
const SCALE_MIN = 0.25;
const SCALE_MAX = 0.75;

function pct(value: number): number {
  const clamped = Math.min(SCALE_MAX, Math.max(SCALE_MIN, value));
  return ((clamped - SCALE_MIN) / (SCALE_MAX - SCALE_MIN)) * 100;
}

const POSITION_TEXT: Record<
  CalibrationPosition,
  { tone: string; headline: string }
> = {
  at_or_above_recovery: {
    tone: "text-positive",
    headline: "At or above the recovery threshold",
  },
  between_thresholds: {
    tone: "text-warning",
    headline: "Between the entry and recovery thresholds",
  },
  at_or_below_entry: {
    tone: "text-failure",
    headline: "At or below the drift entry threshold",
  },
  insufficient_data: {
    tone: "text-text-secondary",
    headline: "Not enough labeled rows to place a reading",
  },
};

function interpretation(health: CalibrationHealthResponse): string {
  const { drift_entry_threshold: entry, recovery_threshold: recovery } = health;
  switch (health.position) {
    case "between_thresholds":
      return `Kappa is above the drift entry line at ${entry.toFixed(2)} and still below the ${recovery.toFixed(2)} needed to count as recovered. The two thresholds differ on purpose, so a reading cannot flip the state by crossing a single value.`;
    case "at_or_below_entry":
      return `Kappa is at or below ${entry.toFixed(2)}, the drift entry line. The judge agrees with the labels noticeably less than its baseline.`;
    case "at_or_above_recovery":
      return `Kappa is at or above the ${recovery.toFixed(2)} recovery line.`;
    case "insufficient_data":
      return `Fewer than ${health.min_n} labeled rows were scored, which is the minimum for a reading.`;
  }
}

/** The question an operator is really asking, answered before any statistic. */
function trustLine(health: CalibrationHealthResponse): string {
  switch (health.position) {
    case "at_or_above_recovery":
      return "Yes. The frontier judge agrees with labeled examples at the level that counts as recovered.";
    case "between_thresholds":
      return "Not fully. The frontier judge’s agreement with labeled examples is above the drift line but has not reached the recovery line.";
    case "at_or_below_entry":
      return "No. The frontier judge agrees with labeled examples less than it should, so treat its verdicts with caution.";
    case "insufficient_data":
      return "Unknown. Too few labeled rows were scored to place a reading.";
  }
}

type MarkerId = "entry" | "recovery" | "baseline" | "kappa";

interface MarkerInfo {
  id: MarkerId;
  label: string;
  value: number;
  /** One sentence on what the marker means, read from the drift policy. */
  meaning: string;
}

function markersFor(health: CalibrationHealthResponse): MarkerInfo[] {
  const markers: MarkerInfo[] = [
    {
      id: "entry",
      label: "Drift entry",
      value: health.drift_entry_threshold,
      meaning:
        "The drift policy puts the judge in drift when agreement stays at or below this line. It is the lower of the two thresholds.",
    },
    {
      id: "recovery",
      label: "Recovery",
      value: health.recovery_threshold,
      meaning:
        "After drift, the judge counts as recovered only when agreement stays at or above this line. It sits above the entry line, so the state has a gap to cross.",
    },
    {
      id: "baseline",
      label: "Healthy baseline",
      value: health.healthy_baseline_kappa,
      meaning:
        "The agreement established on the labeled calibration set. The policy never lets the recovery line sit above it.",
    },
  ];
  if (health.kappa !== null) {
    markers.push({
      id: "kappa",
      label: "Last reading",
      value: health.kappa,
      meaning: `Cohen’s kappa of the frontier judge against labeled financial rows${health.window_n !== null ? `, over ${health.window_n} rows` : ""}. One manual reading, not a live value.`,
    });
  }
  return markers;
}

function digits(m: MarkerInfo): number {
  return m.id === "baseline" || m.id === "kappa" ? 3 : 2;
}

/**
 * The persisted calibration reading drawn against its policy: the drift
 * entry line, the recovery line and the healthy baseline, with the one real
 * kappa on the same axis. It answers "why is the judge in this state".
 * Each marker is a focusable control that explains itself on hover or
 * focus, and a click or tap pins the explanation until it is clicked again
 * or Escape is pressed. The zones sweep in once on entry; nothing here moves
 * afterward. It is one point in time. There is no trend line because only
 * one reading exists on record.
 */
export function CalibrationInstrument({
  health,
}: {
  health: CalibrationHealthResponse | null;
}) {
  const [hovered, setHovered] = useState<MarkerId | null>(null);
  const [focused, setFocused] = useState<MarkerId | null>(null);
  const [pinned, setPinned] = useState<MarkerId | null>(null);
  const active = hovered ?? focused ?? pinned;
  const now = useNow();

  if (!health) {
    return (
      <section id="calibration" aria-labelledby="calibration-heading">
        <h2
          id="calibration-heading"
          className="text-text-primary text-2xl font-semibold tracking-tight"
        >
          Calibration
        </h2>
        <p className="border-failure/40 bg-failure/5 text-text-primary mt-6 rounded-lg border p-5 text-base">
          The calibration reading is not available. The gateway did not return
          it, so no state is shown instead of a guess.
        </p>
      </section>
    );
  }

  const text = POSITION_TEXT[health.position];
  const entry = health.drift_entry_threshold;
  const recovery = health.recovery_threshold;
  const markers = markersFor(health);
  const info = markers.find((m) => m.id === active) ?? null;

  return (
    <section id="calibration" aria-labelledby="calibration-heading">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <h2
          id="calibration-heading"
          className="text-text-primary text-2xl font-semibold tracking-tight"
        >
          Calibration
        </h2>
        <p className="text-text-tertiary text-sm">
          Judge: <span className="font-mono">{health.judge_id}</span> (frontier
          tier). The flash judge is not calibrated.
        </p>
      </div>

      <div
        className="instrument group/shell bg-background-elevated/50 mt-6 rounded-2xl p-6 sm:p-8"
        style={
          {
            "--tone": `var(--${CALIBRATION_POSITION_TONE[health.position]})`,
            "--lift": "1px",
            "--grow": 1.003,
          } as CSSProperties
        }
      >
        <p className="text-text-primary max-w-3xl text-xl leading-snug font-medium text-balance">
          <span className="text-text-tertiary block text-sm font-normal">
            Can the frontier judge be trusted as a second opinion?
          </span>
          {trustLine(health)}
        </p>

        <div className="mt-8 grid gap-x-16 gap-y-10 lg:grid-cols-[18rem_1fr]">
          <div>
            <p className="text-text-tertiary text-sm">Cohen&rsquo;s kappa</p>
            <p className="tabular-metric text-text-primary mt-2 text-6xl font-semibold tracking-tight">
              {health.kappa !== null ? health.kappa.toFixed(3) : "n/a"}
            </p>
            <p className={`mt-3 text-base font-medium ${text.tone}`}>
              {health.state ? `State: ${health.state}` : "No state recorded"}
            </p>
            <p className="text-text-secondary mt-1 text-sm">
              {health.window_n !== null
                ? `${health.window_n} labeled rows scored (minimum ${health.min_n})`
                : `Minimum ${health.min_n} labeled rows`}
            </p>
          </div>

          <div>
            {health.kappa !== null ? (
              <div
                role="group"
                aria-label={`Kappa ${health.kappa.toFixed(3)} on a scale from ${SCALE_MIN} to ${SCALE_MAX}. Drift entry threshold ${entry.toFixed(2)}, recovery threshold ${recovery.toFixed(2)}, healthy baseline ${health.healthy_baseline_kappa.toFixed(3)}. Each marker explains itself on focus.`}
                className="relative mt-20 mb-24 h-3"
                onKeyDown={(e) => {
                  if (e.key === "Escape") {
                    setPinned(null);
                    setHovered(null);
                  }
                }}
              >
                <div className="bg-surface absolute inset-0 overflow-hidden rounded-full">
                  <div className="pointer-events-none absolute inset-0 bg-white/10 opacity-0 transition-opacity duration-[var(--dur-base)] group-focus-within/shell:opacity-100 group-hover/shell:opacity-100" />
                  <div className="enter-sweep absolute inset-0">
                    <div
                      className="bg-failure/35 absolute inset-y-0 left-0"
                      style={{ width: `${pct(entry)}%` }}
                    />
                    <div
                      className="bg-warning/35 absolute inset-y-0"
                      style={{
                        left: `${pct(entry)}%`,
                        width: `${pct(recovery) - pct(entry)}%`,
                      }}
                    />
                    <div
                      className="bg-positive/30 absolute inset-y-0 right-0"
                      style={{ left: `${pct(recovery)}%` }}
                    />
                  </div>
                </div>

                {markers.map((m) => {
                  const isActive = active === m.id;
                  const isKappa = m.id === "kappa";
                  return (
                    <button
                      key={m.id}
                      type="button"
                      aria-label={`${m.label} ${m.value.toFixed(digits(m))}. ${m.meaning}`}
                      aria-pressed={pinned === m.id}
                      onPointerEnter={(e) => {
                        if (e.pointerType === "mouse") setHovered(m.id);
                      }}
                      onPointerLeave={(e) => {
                        if (e.pointerType === "mouse") setHovered(null);
                      }}
                      onFocus={(e) => {
                        // A click or tap also focuses the button, and the pin
                        // handles that. Only keyboard focus shows it here.
                        if (e.currentTarget.matches(":focus-visible")) {
                          setFocused(m.id);
                        }
                      }}
                      onBlur={() => setFocused(null)}
                      onClick={() =>
                        setPinned((p) => (p === m.id ? null : m.id))
                      }
                      className={`group absolute top-1/2 flex h-11 w-11 -translate-x-1/2 -translate-y-1/2 items-center justify-center rounded-full ${isKappa ? "enter-fade z-10" : ""}`}
                      style={
                        {
                          left: `${pct(m.value)}%`,
                          "--i": 14,
                        } as React.CSSProperties
                      }
                    >
                      {isKappa ? (
                        <span
                          className={`bg-text-primary border-background block h-6 w-1.5 rounded-full border-2 transition-transform duration-[var(--dur-base)] ease-[var(--ease)] ${isActive ? "scale-y-125 scale-x-150" : ""}`}
                        />
                      ) : (
                        <span
                          className={`block h-5 transition-[width,background-color] duration-[var(--dur-base)] ${m.id === "baseline" ? "border-text-tertiary border-l border-dashed" : `w-px ${isActive ? "bg-text-primary scale-x-[3]" : "bg-text-secondary"}`}`}
                        />
                      )}
                    </button>
                  );
                })}

                {markers
                  .filter((m) => m.id !== "kappa")
                  .map((m) => (
                    <div
                      key={m.id}
                      aria-hidden="true"
                      className={`absolute top-full pt-3 transition-opacity duration-[var(--dur-base)] ${m.id === "entry" ? "-translate-x-full" : m.id === "baseline" ? "" : "-translate-x-1/2"} ${active && active !== m.id ? "opacity-40" : "opacity-100"}`}
                      style={{ left: `${pct(m.value)}%` }}
                    >
                      <p className="text-text-secondary text-xs whitespace-nowrap">
                        {m.label}
                      </p>
                      <p className="tabular-metric text-text-primary text-sm">
                        {m.value.toFixed(digits(m))}
                      </p>
                    </div>
                  ))}

                <div
                  aria-hidden="true"
                  className="absolute bottom-full -translate-x-1/2 pb-2"
                  style={{ left: `${pct(health.kappa)}%` }}
                >
                  <p className="tabular-metric text-text-primary text-sm font-semibold whitespace-nowrap">
                    kappa {health.kappa.toFixed(3)}
                  </p>
                </div>

                <div
                  aria-hidden="true"
                  className="text-text-tertiary absolute top-full right-0 left-0 mt-16 flex justify-between font-mono text-[11px]"
                >
                  <span>{SCALE_MIN.toFixed(2)}</span>
                  <span>
                    scale {SCALE_MIN.toFixed(2)} to {SCALE_MAX.toFixed(2)}, not
                    the full kappa range
                  </span>
                  <span>{SCALE_MAX.toFixed(2)}</span>
                </div>

                <div
                  aria-live="polite"
                  className="pointer-events-none absolute z-20"
                  style={{
                    left: `${info ? Math.min(78, Math.max(22, pct(info.value))) : 50}%`,
                    bottom: "calc(100% + 2.75rem)",
                  }}
                >
                  {info ? (
                    <div className="floating swap-in w-72 -translate-x-1/2 rounded-lg px-4 py-3">
                      <p className="text-text-primary text-sm font-semibold">
                        {info.label}{" "}
                        <span className="tabular-metric text-text-secondary font-normal">
                          {info.value.toFixed(digits(info))}
                        </span>
                      </p>
                      <p className="text-text-secondary mt-1 text-sm leading-snug">
                        {info.meaning}
                      </p>
                    </div>
                  ) : null}
                </div>
              </div>
            ) : null}

            <p className={`text-lg font-medium ${text.tone}`}>
              {text.headline}
            </p>
            <p className="text-text-secondary mt-2 max-w-2xl text-base leading-relaxed">
              {interpretation(health)}
            </p>
          </div>
        </div>

        <dl className="border-border mt-10 grid gap-x-10 gap-y-4 border-t pt-6 text-sm sm:grid-cols-[auto_1fr]">
          <dt className="text-text-tertiary">Persisted</dt>
          <dd className="text-text-secondary">
            {health.state_as_of
              ? `${formatUtc(health.state_as_of)}${now !== null ? `, ${relativeTime(health.state_as_of, now)}` : ""}`
              : "No timestamp recorded"}
          </dd>
          <dt className="text-text-tertiary">Provenance</dt>
          <dd className="text-text-secondary max-w-3xl">
            One manual canary run read from a file on disk. It is not a
            scheduled or continuously running monitor, and no earlier readings
            are persisted, so there is no trend to draw. The service reports:
            &ldquo;
            {health.note}&rdquo;
          </dd>
        </dl>
      </div>
    </section>
  );
}
