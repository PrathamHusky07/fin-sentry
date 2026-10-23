import "server-only";
import { serveArchive } from "@/lib/archive/serve";
import { ARCHIVE_MODE } from "@/lib/archive-mode";
import { GATEWAY_URL } from "@/lib/config";

/**
 * The way a Server Component reads an /ops route. Live, it is a plain fetch to the gateway. In
 * archived-evidence mode the archive is read in process, with no network request at all, so
 * nothing can reach a gateway and no function needs to call its own site.
 */
export function serverOpsFetch(
  path: string,
  init?: RequestInit,
): Promise<Response> {
  if (!ARCHIVE_MODE) return fetch(`${GATEWAY_URL}${path}`, init);
  return serveArchive(path);
}
