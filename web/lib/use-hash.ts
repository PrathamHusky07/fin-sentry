"use client";

import { useSyncExternalStore } from "react";

function subscribe(onChange: () => void): () => void {
  window.addEventListener("hashchange", onChange);
  return () => window.removeEventListener("hashchange", onChange);
}

function getSnapshot(): string {
  return window.location.hash.slice(1);
}

function getServerSnapshot(): string {
  return "";
}

/** The current URL fragment without the `#`, or an empty string during
 * server render. A client-side navigation does not set CSS `:target`, so a
 * component that highlights its anchor reads the fragment here instead. */
export function useHash(): string {
  return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
