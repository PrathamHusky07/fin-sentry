import { ARCHIVE_MODE } from "@/lib/archive-mode";
import { GATEWAY_URL } from "@/lib/config";

/**
 * The way a client component, or code that runs only in the browser, reads or calls an /ops
 * route. Live, it is a plain fetch to the gateway. In archived-evidence mode nothing is sent to a
 * gateway: the browser asks this site's own /api/archive route, which reads the bundled archive.
 * The mode is fixed at build time. Server code uses serverOpsFetch, so no browser bundle can
 * reach the archive files.
 */
export function opsFetch(path: string, init?: RequestInit): Promise<Response> {
  if (!ARCHIVE_MODE) return fetch(`${GATEWAY_URL}${path}`, init);
  return fetch(`/api/archive${path.replace(/^\/ops/, "")}`, init);
}
