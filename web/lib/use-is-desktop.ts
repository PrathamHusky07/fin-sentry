import { useSyncExternalStore } from "react";

/** True from the lg breakpoint up. The server renders the narrow layout and the client
 * switches after hydration without a mismatch. */
export function useIsDesktop(): boolean {
  return useSyncExternalStore(
    (notify) => {
      const query = window.matchMedia("(min-width: 1024px)");
      query.addEventListener("change", notify);
      return () => query.removeEventListener("change", notify);
    },
    () => window.matchMedia("(min-width: 1024px)").matches,
    () => false,
  );
}
