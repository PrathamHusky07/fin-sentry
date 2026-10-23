import { ARCHIVE_MODE } from "@/lib/archive-mode";
import { serveArchive } from "@/lib/archive/serve";

/**
 * The read-only answers of archived-evidence mode, under /api/archive/<gateway /ops path>. It
 * serves nothing unless the mode is switched on at build time, and it exports GET only, so a POST
 * to it is refused by the framework.
 */
export async function GET(
  request: Request,
  context: RouteContext<"/api/archive/[...path]">,
): Promise<Response> {
  if (!ARCHIVE_MODE) {
    return Response.json(
      { error: "archived evidence is not enabled" },
      { status: 404 },
    );
  }
  const { path } = await context.params;
  const search = new URL(request.url).search;
  return serveArchive(`/ops/${path.join("/")}${search}`);
}
