import { defineConfig } from "@playwright/test";

/**
 * These are real-stack integration checks, not CI unit tests: they require
 * the dashboard, RisingWave, and the gateway actually running (see
 * CLAUDE.md's Commands section), plus `npm run dev` for this app. Run
 * manually with `npx playwright test` once that stack is up -- there is no
 * webServer/mock harness here, deliberately: a mocked server would prove
 * nothing about the real SSE path.
 *
 * Resource safety: one worker, no parallelism, stop at the first failure.
 * A previous session ran parallel browsers against the live stack and
 * caused memory pressure severe enough to evict a RisingWave worker.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 20_000,
  workers: 1,
  fullyParallel: false,
  maxFailures: 1,
  retries: 0,
  use: {
    baseURL: "http://localhost:3000",
  },
});
