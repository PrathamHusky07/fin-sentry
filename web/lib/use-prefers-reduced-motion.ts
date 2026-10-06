"use client";

import { useSyncExternalStore } from "react";

const QUERY = "(prefers-reduced-motion: reduce)";

function subscribe(onChange: () => void): () => void {
  const query = window.matchMedia(QUERY);
  query.addEventListener("change", onChange);
  return () => query.removeEventListener("change", onChange);
}

function getSnapshot(): boolean {
  return window.matchMedia(QUERY).matches;
}

function getServerSnapshot(): boolean {
  return false;
}

/** Shared reduced-motion check for the few places motion is driven by JS
 * (Recharts animations, the landing page's pipeline-flow sequencing)
 * rather than pure CSS, where `motion-reduce:`/`@media` already apply on
 * their own. useSyncExternalStore, not useState+useEffect, since this is
 * exactly a subscription to external browser state. */
export function usePrefersReducedMotion(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
