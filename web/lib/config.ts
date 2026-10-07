/**
 * The gateway's browser-facing base URL -- where EventSource connects for
 * the Live Operations SSE feed (GET /ops/stream). Falls back to the
 * gateway's documented port (see root CLAUDE.md's Commands section) so the
 * app runs with no .env file. Set NEXT_PUBLIC_GATEWAY_URL to point at any
 * other topology (e.g. the nginx-fronted replica set).
 */
export const GATEWAY_URL: string =
  process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:8000";
