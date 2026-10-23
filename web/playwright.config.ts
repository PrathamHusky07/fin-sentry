import { defineConfig } from "@playwright/test";

/**
 * These are real-stack integration checks, not CI unit tests: they require
 * the dashboard, RisingWave, and the gateway actually running (see
 * CLAUDE.md's Commands section), plus `npm run dev` for this app. Run
 * manually with `npx playwright test` once that stack is up -- there is no
 * webServer/mock harness here, deliberately: a mocked server would prove
 * nothing about the real SSE path.
 *
 * The "archive" project is the one exception to "real stack". It tests archived-evidence mode
 * against a production build made with NEXT_PUBLIC_ARCHIVE_MODE=true and a closed port as the
 * gateway, served on :3100, so a stray gateway call fails loudly. Build and serve it first:
 * `npm run build:archive` then `npm run start:archive`, with the Next dev server stopped while
 * the build runs. `npm run test:e2e:archive` runs only that project.
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
  projects: [
    {
      name: "live",
      testIgnore: /archive-.*\.spec\.ts/,
      use: { baseURL: "http://localhost:3000" },
    },
    {
      name: "archive",
      testMatch: /archive-.*\.spec\.ts/,
      use: { baseURL: "http://localhost:3100" },
    },
  ],
});
