"use client";

import Link from "next/link";
import { useSyncExternalStore, type ReactNode } from "react";

// The architecture page swaps its request-path diagram for an outline below
// this width (Tailwind `lg`), and the two use different anchor ids.
const WIDE = "(min-width: 1024px)";

function subscribe(onChange: () => void): () => void {
  const query = window.matchMedia(WIDE);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

function getSnapshot(): boolean {
  return window.matchMedia(WIDE).matches;
}

function getServerSnapshot(): boolean {
  return false;
}

/** A link whose target depends on which layout of the destination page the
 * viewport will see. `narrowHref` is used below the wide breakpoint and is
 * also what the server renders, until hydration reads the real width. */
export function StageLink({
  href,
  narrowHref,
  className,
  children,
}: {
  href: string;
  narrowHref?: string;
  className: string;
  children: ReactNode;
}) {
  const wide = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
  return (
    <Link href={wide ? href : (narrowHref ?? href)} className={className}>
      {children}
    </Link>
  );
}
