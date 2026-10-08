/**
 * The gateway's base URL. Two defaults, because there are two callers:
 *
 * - Browser (EventSource on /ops/stream, client-side fetches): "", meaning
 *   same-origin. next.config.ts rewrites /ops/* to the gateway, so the
 *   browser never makes a cross-origin call and the gateway's CORS allowlist
 *   (which names only http://localhost:3000) stops mattering. Opening the app
 *   as http://127.0.0.1:3000 or from a phone on the LAN works the same way.
 * - Server (Server Components in lib/overview-data.ts, running in Node):
 *   the gateway's documented port (see root CLAUDE.md's Commands section),
 *   because a relative URL cannot be fetched from Node.
 *
 * Set NEXT_PUBLIC_GATEWAY_URL to point both at any other topology (e.g. the
 * nginx-fronted replica set). That override wins everywhere and bypasses the
 * rewrite.
 */
const LOCAL_GATEWAY_URL = "http://localhost:8000";

export const GATEWAY_URL: string =
  process.env.NEXT_PUBLIC_GATEWAY_URL ??
  (typeof window === "undefined" ? LOCAL_GATEWAY_URL : "");
