"use client";

import { useRef, useState, type CSSProperties } from "react";
import {
  READING_STATES,
  readingStateById,
  type ReadingId,
  type ReadingState,
} from "@/lib/agent-view";
import { useIsDesktop } from "@/lib/use-is-desktop";

// The border of each state is its meaning: solid says something about the platform, dashed
// says nothing about it. The five query states keep the borders the case file has always used.
const BORDER: Record<ReadingId, string> = {
  returned: "border-border-strong",
  verified_empty: "border-border-strong",
  hypothesis: "border-border-strong",
  unverified_empty: "border-dashed border-warning/60",
  unavailable: "border-dashed border-failure/50",
  rejected: "border-dashed border-border-strong",
  abstained: "border-dashed border-border-strong",
};

const TONE: Record<ReadingId, string> = {
  returned: "var(--accent)",
  verified_empty: "var(--accent)",
  hypothesis: "var(--accent)",
  unverified_empty: "var(--warning)",
  unavailable: "var(--failure)",
  rejected: "var(--text-secondary)",
  abstained: "var(--text-secondary)",
};

const KIND_LABEL: Record<ReadingState["kind"], string> = {
  query: "Query result",
  outcome: "Outcome",
};

type TileState = "rest" | "active" | "quiet";

function Tile({
  reading,
  state,
  pinned,
  expanded,
  onPin,
  onPreview,
  onStep,
  tileRef,
}: {
  reading: ReadingState;
  state: TileState;
  /** True for the state that was selected. */
  pinned: boolean;
  /** Set on the narrow layout, where the explanation opens in place. Null on the wide one. */
  expanded: boolean | null;
  onPin: () => void;
  /** Called with this state on hover and keyboard focus, and with null on leave and blur. */
  onPreview: (on: boolean) => void;
  onStep: (direction: 1 | -1) => void;
  tileRef: (el: HTMLButtonElement | null) => void;
}) {
  return (
    <button
      ref={tileRef}
      type="button"
      data-state={state}
      data-reading={reading.id}
      aria-pressed={pinned}
      aria-expanded={expanded ?? undefined}
      aria-controls="reading-detail"
      style={{ ["--tone" as string]: TONE[reading.id] } as CSSProperties}
      className={`rc-tile bg-background-elevated/50 flex min-h-16 w-full flex-col items-start justify-center gap-0.5 rounded-lg border px-4 py-3 text-left ${BORDER[reading.id]}`}
      onClick={onPin}
      onPointerEnter={(e) => {
        if (e.pointerType === "mouse") onPreview(true);
      }}
      onPointerLeave={(e) => {
        if (e.pointerType === "mouse") onPreview(false);
      }}
      onFocus={(e) => {
        if (e.currentTarget.matches(":focus-visible")) onPreview(true);
      }}
      onBlur={() => onPreview(false)}
      onKeyDown={(e) => {
        if (e.key === "ArrowRight" || e.key === "ArrowDown") {
          e.preventDefault();
          onStep(1);
        } else if (e.key === "ArrowLeft" || e.key === "ArrowUp") {
          e.preventDefault();
          onStep(-1);
        }
      }}
    >
      <span className="text-text-tertiary text-base sm:text-sm">
        {KIND_LABEL[reading.kind]}
      </span>
      <span className="text-text-primary text-base leading-snug font-medium">
        {reading.label}
      </span>
    </button>
  );
}

function ReadingPanel({
  reading,
  previewing,
}: {
  reading: ReadingState;
  previewing: boolean;
}) {
  return (
    <div
      id="reading-detail"
      role="region"
      // A preview follows the pointer, so announcing each one would talk over the person.
      aria-live={previewing ? "off" : "polite"}
      aria-label={reading.label}
      style={{ ["--tone" as string]: TONE[reading.id] } as CSSProperties}
      className="instrument border-line bg-background-elevated/70 swap-in rounded-xl p-5 sm:p-6"
      key={reading.id}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span
          aria-hidden="true"
          className={`inline-block h-3.5 w-8 rounded-sm border ${BORDER[reading.id]}`}
        />
        <p className="text-text-secondary text-base sm:text-sm">
          {KIND_LABEL[reading.kind]}.{" "}
          {reading.says
            ? "Says something about the platform."
            : "Says nothing about the platform."}
        </p>
        {previewing ? (
          <span className="text-text-tertiary text-base sm:text-sm">
            Preview. Click or press Enter to keep this one.
          </span>
        ) : null}
      </div>
      <h3 className="text-text-primary mt-2 text-xl font-semibold tracking-tight">
        {reading.label}
      </h3>
      <p className="text-text-secondary mt-2 max-w-prose text-base leading-relaxed text-pretty">
        {reading.meaning}
      </p>
    </div>
  );
}

function BandHeading({
  solid,
  children,
}: {
  solid: boolean;
  children: string;
}) {
  return (
    <h3 className="text-text-secondary mb-2 flex items-center gap-2.5 text-base sm:text-sm">
      <span
        aria-hidden="true"
        className={`inline-block h-3 w-7 rounded-sm border border-border-strong ${solid ? "" : "border-dashed"}`}
      />
      {children}
    </h3>
  );
}

/**
 * What a case file can say, as one hierarchy. The top band holds what says something about
 * the platform (solid border), the bottom band holds what says nothing about it (dashed
 * border). Pointing at or focusing a state brings it forward, quiets the rest and shows what
 * it means. A click or Enter keeps it, arrow keys move between states, and reduced motion
 * keeps the state without the lift. Narrow screens have no hover, so the selected state
 * opens in place. This is a key to the labels, not a record of any case.
 */
export function ReadingACase() {
  const [selected, setSelected] = useState<ReadingId>("returned");
  const [preview, setPreview] = useState<ReadingId | null>(null);
  const desktop = useIsDesktop();
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  // Derived during render: the preview shows at once on a wide screen, and the kept state
  // returns when the pointer or focus leaves.
  const shown: ReadingId = desktop && preview ? preview : selected;
  const reading = readingStateById(shown);

  const tiles = READING_STATES.map((r, i) => {
    const state: TileState =
      r.id === shown ? "active" : desktop ? "quiet" : "rest";
    return (
      <Tile
        key={r.id}
        reading={r}
        state={state}
        pinned={selected === r.id}
        expanded={desktop ? null : selected === r.id}
        onPin={() => setSelected(r.id)}
        onPreview={(on) =>
          setPreview((current) =>
            on ? r.id : current === r.id ? null : current,
          )
        }
        onStep={(direction) =>
          refs.current[
            (i + direction + READING_STATES.length) % READING_STATES.length
          ]?.focus()
        }
        tileRef={(el) => {
          refs.current[i] = el;
        }}
      />
    );
  });
  const says = READING_STATES.map((r, i) => ({ r, tile: tiles[i] })).filter(
    ({ r }) => r.says,
  );
  const silent = READING_STATES.map((r, i) => ({ r, tile: tiles[i] })).filter(
    ({ r }) => !r.says,
  );

  const band = (
    items: typeof says,
    columns: string,
    label: string,
    solid: boolean,
  ) => (
    <div>
      <BandHeading solid={solid}>{label}</BandHeading>
      <ul className={`grid gap-3 ${columns}`}>
        {items.map(({ r, tile }) => (
          <li key={r.id}>
            {tile}
            {!desktop && selected === r.id ? (
              <div className="mt-2">
                <ReadingPanel reading={r} previewing={false} />
              </div>
            ) : null}
          </li>
        ))}
      </ul>
    </div>
  );

  return (
    <div>
      <h2
        id="guide-heading"
        className="text-text-primary text-2xl font-semibold tracking-tight text-balance"
      >
        Reading a case file
      </h2>
      <p className="text-text-secondary mt-2 max-w-3xl text-base leading-relaxed text-pretty">
        A solid border says something about the platform. A dashed border says
        nothing about it.{" "}
        {desktop
          ? "Point at a state to read what it means, and select one to keep it."
          : "Select a state to read what it means."}
      </p>
      <div className="mt-6 space-y-6">
        {band(
          says,
          "sm:grid-cols-3",
          "Says something about the platform",
          true,
        )}
        {band(
          silent,
          "sm:grid-cols-2 lg:grid-cols-4",
          "Says nothing about the platform",
          false,
        )}
      </div>
      {desktop ? (
        <div className="mt-6">
          <ReadingPanel reading={reading} previewing={shown !== selected} />
        </div>
      ) : null}
    </div>
  );
}
