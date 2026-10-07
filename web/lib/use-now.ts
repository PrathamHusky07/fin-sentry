"use client";

import { useSyncExternalStore } from "react";

function subscribe(onChange: () => void): () => void {
  const id = setInterval(onChange, 1000);
  return () => clearInterval(id);
}

function getSnapshot(): number {
  return Math.floor(Date.now() / 1000) * 1000;
}

function getServerSnapshot(): null {
  return null;
}

/** The browser clock, ticking once a second, or null during server render
 * and hydration. Ages ("12s ago") derived from it are computed only on the
 * client, so server and client markup never disagree about the time. */
export function useNow(): number | null {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
