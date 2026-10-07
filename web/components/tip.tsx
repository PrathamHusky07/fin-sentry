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
  label: string;
  definition: string;
  children: ReactNode;
  className?: string;
  /** False when the child is already a focusable control, so the trigger
   * does not add a second tab stop. The tooltip still opens on its focus. */
  focusable?: boolean;
}) {
  const id = useId();
  const [open, setOpen] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  function show(delay: number) {
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setOpen(true), delay);
  }

  function hide() {
    if (timer.current) clearTimeout(timer.current);
    setOpen(false);
  }

  return (
    <span
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
        data-open={open}
        className="tip floating bottom-full left-0 mb-2 w-max max-w-64 rounded-lg px-3 py-2"
      >
        <span className="text-text-primary block text-sm font-semibold">
          {label}
        </span>
        <span className="text-text-secondary mt-0.5 block text-sm leading-snug font-normal">
          {definition}
        </span>
      </span>
    </span>
  );
}
