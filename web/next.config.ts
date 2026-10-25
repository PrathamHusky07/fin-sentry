import { existsSync } from "node:fs";
import path from "node:path";
import type { NextConfig } from "next";

// The browser calls /ops/* on its own origin (see lib/config.ts) and Next
// proxies it to the gateway, so fetch and EventSource never cross origins.
const gatewayUrl =
  process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:8000";

// Archived-evidence mode (lib/archive-mode.ts): the site serves a read-only copy of the committed
// archive and sends nothing to a gateway, so the /ops rewrite below is switched off.
const archiveMode = process.env.NEXT_PUBLIC_ARCHIVE_MODE === "true";

// The archive files, by who reads them. Every module that can reach lib/archive/files.ts is
// traced with all ten paths, so each page that reads the archive on the server excludes the
// groups it does not use, and only the route handler carries all of them.
const ARCHIVE_FILES = {
  streams: [
    "../docs/demo-archive/stream/rag-responses.jsonl",
    "../docs/demo-archive/stream/judge-verdicts.jsonl",
    "../docs/demo-archive/stream/rag-frontier-verdicts.jsonl",
  ],
  calibration: ["../docs/measurements/reliability/canary-live-smoke-d6p2.json"],
  investigations: ["../docs/demo-archive/postgres/investigations.jsonl"],
  timelines: ["../docs/demo-archive/postgres/investigation_events.jsonl"],
  // The recorded gateway probe row. Only Live Operations reads it.
  probe: ["../docs/demo-archive/postgres/gateway_probe_runs.jsonl"],
  redTeam: [
    "../docs/demo-archive/postgres/red_team_runs.jsonl",
    "../docs/demo-archive/postgres/red_team_executions.jsonl",
    "../finsentry/redteam/scenarios.yml",
  ],
};
type ArchiveGroup = keyof typeof ARCHIVE_FILES;
const allArchiveFiles = Object.values(ARCHIVE_FILES).flat();
const archiveExcept = (...keep: ArchiveGroup[]) =>
  Object.entries(ARCHIVE_FILES)
    .filter(([group]) => !keep.includes(group as ArchiveGroup))
    .flatMap(([, files]) => files);
// Route keys are globs, so the brackets of the catch-all segment are escaped.
const ARCHIVE_ROUTE = "/api/archive/\\[\\.\\.\\.path\\]";

// A build that cannot see the committed files would trace nothing and ship pages that all say
// "unavailable", so it stops here with the reason instead.
if (
  archiveMode &&
  !existsSync(
    path.join(process.cwd(), "..", "docs", "demo-archive", "manifest.json"),
  )
) {
  throw new Error(
    "Archived-evidence mode needs docs/demo-archive next to this directory. On Vercel, enable including source files outside the Root Directory.",
  );
}

const nextConfig: NextConfig = {
  // A second build directory lets the archived build sit beside the live one.
  distDir: process.env.NEXT_DIST_DIR ?? ".next",
  ...(archiveMode && {
    outputFileTracingRoot: path.join(process.cwd(), ".."),
    outputFileTracingIncludes: { [ARCHIVE_ROUTE]: allArchiveFiles },
    outputFileTracingExcludes: {
      "/overview": archiveExcept("streams", "calibration"),
      "/operations": archiveExcept("streams", "calibration", "probe"),
      "/generation": archiveExcept("streams"),
      "/agent": archiveExcept("investigations"),
    },
  }),
  // Browsers send Accept-Encoding: gzip, and Next's gzip layer buffers the
  // proxied /ops/stream response, so no SSE snapshot ever reaches the page.
  // Vercel compresses at its edge in the deployed topology.
  compress: false,
  // Dev only: without this, Next blocks /_next/hmr and the client never
  // hydrates when the app is opened as http://127.0.0.1:3000.
  allowedDevOrigins: ["127.0.0.1"],
  // The incident workspace moved from the Investigations area to the Agent route. The old
  // paths keep working, and a stored link to one session still opens it.
  async redirects() {
    return [
      {
        source: "/investigations/incidents",
        destination: "/agent",
        permanent: false,
      },
      {
        source: "/investigations/incidents/:id",
        destination: "/agent/:id",
        permanent: false,
      },
    ];
  },
  async rewrites() {
    if (archiveMode) return [];
    return [{ source: "/ops/:path*", destination: `${gatewayUrl}/ops/:path*` }];
  },
};

export default nextConfig;
