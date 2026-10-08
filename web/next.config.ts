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
  async rewrites() {
    return [{ source: "/ops/:path*", destination: `${gatewayUrl}/ops/:path*` }];
  },
};

export default nextConfig;
