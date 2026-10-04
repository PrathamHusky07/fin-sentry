/**
 * The gateway's browser-facing base URL -- where EventSource connects for
 * the Live Operations SSE feed (GET /ops/stream). Defaults to the gateway's
 * documented local-dev port (see root CLAUDE.md's Commands section) so
 * local dev works with no .env file. Override with NEXT_PUBLIC_GATEWAY_URL
 * for other topologies (e.g. the Gate D nginx-fronted replica set).
 */
export const GATEWAY_URL: string =
  process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:8000";
