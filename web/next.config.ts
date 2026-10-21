import type { NextConfig } from "next";

// The browser calls /ops/* on its own origin (see lib/config.ts) and Next
// proxies it to the gateway, so fetch and EventSource never cross origins.
const gatewayUrl =
  process.env.NEXT_PUBLIC_GATEWAY_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
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
    return [{ source: "/ops/:path*", destination: `${gatewayUrl}/ops/:path*` }];
  },
};

export default nextConfig;
