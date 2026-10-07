"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

/**
 * Holds the one-shot entrance animations inside it until the block first
 * scrolls into view, then lets them run once. Without it, an instrument
 * below the fold would finish animating before anyone saw it. Reduced
 * motion removes the animations themselves, so there is nothing to hold.
 */
export function InView({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  const [seen, setSeen] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (!el || seen) return;
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setSeen(true);
          observer.disconnect();
        }
      },
      { threshold: 0.15 },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [seen]);

  return (
    <div ref={ref} data-seen={seen} className={`view-gate ${className}`}>
      {children}
    </div>
  );
}
