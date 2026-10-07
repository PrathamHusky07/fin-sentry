"use client";

import {
  useRef,
  useState,
  type CSSProperties,
  type FocusEvent,
  type PointerEvent,
  type ReactNode,
} from "react";

interface Plate {
  top: number;
  height: number;
  tone: string;
  visible: boolean;
  /** True when the plate appears from nowhere, so it should not slide in. */
  instant: boolean;
}

const HIDDEN: Plate = {
  top: 0,
  height: 0,
  tone: "var(--accent)",
  visible: false,
  instant: true,
};

/**
 * A list whose rows share one moving highlight. A row opts in with
 * `data-plate-row` and may set `data-tone` to the name of a color token
 * (failure, warning, disagreement, info, accent). The plate follows a mouse
 * pointer or keyboard focus and is absent on touch, where there is no hover
 * to follow. It moves with transform only.
 */
export function HoverList({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  const host = useRef<HTMLDivElement>(null);
  const [plate, setPlate] = useState<Plate>(HIDDEN);

  function place(row: HTMLElement) {
    const box = host.current;
    if (!box) return;
    const top =
      row.getBoundingClientRect().top - box.getBoundingClientRect().top;
    const tone = row.dataset.tone
      ? `var(--${row.dataset.tone})`
      : "var(--accent)";
    setPlate((prev) => ({
      top,
      height: row.offsetHeight,
      tone,
      visible: true,
      instant: !prev.visible,
    }));
  }

  const rowOf = (target: EventTarget) =>
    (target as HTMLElement).closest<HTMLElement>("[data-plate-row]");

  function onPointerOver(e: PointerEvent<HTMLDivElement>) {
    if (e.pointerType !== "mouse") return;
    const row = rowOf(e.target);
    if (row) place(row);
  }

  function onFocus(e: FocusEvent<HTMLDivElement>) {
    const row = rowOf(e.target);
    if (row && (e.target as HTMLElement).matches(":focus-visible")) place(row);
  }

  const hide = () => setPlate((prev) => ({ ...prev, visible: false }));

  return (
    <div
      ref={host}
      onPointerOver={onPointerOver}
      onPointerLeave={hide}
      onFocusCapture={onFocus}
      onBlurCapture={hide}
      className={`relative isolate ${className}`}
    >
      <span
        aria-hidden="true"
        data-instant={plate.instant}
        className="hover-plate pointer-events-none absolute inset-x-0 top-0 -z-10 rounded-lg"
        style={
          {
            height: plate.height,
            transform: `translateY(${plate.top}px)`,
            opacity: plate.visible ? 1 : 0,
            "--plate-tone": plate.tone,
          } as CSSProperties
        }
      />
      {children}
    </div>
  );
}
