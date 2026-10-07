"use client";

import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

/**
 * A tooltip that explains: a label and a one-line definition, always above
 * the trigger and left-aligned with it. It appears after a short hover delay,
 * immediately on keyboard focus, hides on Escape and is wired to the trigger
 * with aria-describedby. The trigger is focusable so keyboard users get the
 * same definition. Use it for terms and badges outside tables, where an extra
 * tab stop would get in the way of row navigation.
 */
export function Tip({
  label,
  definition,
  children,
  className = "",
  focusable = true,
}: {
  /** A heading for the tooltip. Leave it out when the trigger already says
   * what is being defined, so the term is not repeated. */
  label?: string;
  definition: string;
  children: ReactNode;
  className?: string;
  /** False when the child is already a focusable control, so the trigger
   * does not add a second tab stop. The tooltip still opens on its focus. */
  focusable?: boolean;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const [alignRight, setAlignRight] = useState(false);
  const host = useRef<HTMLSpanElement>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  function show(delay: number) {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => {
      // Open toward the side of the trigger that has room, so the tooltip
      // never runs past the viewport.
      const rect = host.current?.getBoundingClientRect();
      setAlignRight(rect ? rect.left + 256 > window.innerWidth - 16 : false);
      setOpen(true);
    }, delay);
  }

  function hide() {
    if (timer.current) clearTimeout(timer.current);
    setOpen(false);
  }

  return (
    <span
      ref={host}
      className={`relative inline-flex ${className}`}
      onPointerEnter={(e) => {
        if (e.pointerType === "mouse") show(260);
      }}
      onPointerLeave={hide}
      onFocus={() => show(0)}
      onBlur={hide}
      onKeyDown={(e: KeyboardEvent) => {
        if (e.key === "Escape") hide();
      }}
    >
      <span
        tabIndex={focusable ? 0 : undefined}
        aria-describedby={id}
        className={
          focusable
            ? "cursor-help rounded-sm decoration-dotted underline-offset-4 hover:underline focus-visible:underline"
            : undefined
        }
      >
        {children}
      </span>
      <span
        id={id}
        role="tooltip"
        className={`floating pointer-events-none absolute bottom-full z-30 mb-2 w-max max-w-64 rounded-lg px-3 py-2 ${alignRight ? "right-0" : "left-0"} ${open ? "swap-in block" : "hidden"}`}
      >
        {label ? (
          <span className="text-text-primary block text-sm font-semibold">
            {label}
          </span>
        ) : null}
        <span
          className={`text-text-secondary block text-sm leading-snug font-normal ${label ? "mt-0.5" : ""}`}
        >
          {definition}
        </span>
      </span>
    </span>
  );
}
