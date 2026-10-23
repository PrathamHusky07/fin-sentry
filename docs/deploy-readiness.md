# Deploy readiness

Written at the end of Day 12 Session 6, audited again in Session 8 and extended in Session 9 with archived-evidence mode. Nothing is deployed. The Next.js frontend builds, and the checks below ran against the local stack. The gateway, Postgres, Redpanda, RisingWave and the local model do not run on Vercel and are not hosted anywhere.

Git state at the start of Session 8: `main`, `HEAD` and `origin/main` were all `0c7670a`, so the Session 7 commits were already pushed. The Session 8 commits sit on top of it locally and are not pushed.

## Release gate: secret audit

**Result: no secret found in the paths and history scanned.** That is a narrower claim than "safe to publish", and the limits are listed below.

What was scanned again in Session 8, before the repository goes public:

- The working tree and every commit on every ref: 413 commits, three refs (`main`, `origin/main`, `origin/HEAD`), no stash.
- The exact values of `RED_TEAM_RUN_PASSWORD` and `HF_TOKEN` from the local `.env`, in the tree and with a history pickaxe. Neither appears anywhere. `EDGAR_IDENTITY` is the placeholder `fin-sentry noreply@fin-sentry.local` and matches only that placeholder. `DATABASE_URL` and `TEST_DATABASE_URL` are the local `postgres:postgres@localhost` defaults and appear in tests and two scripts.
- Token shapes across all 194,496 added lines in history: Google API keys, GitHub tokens, Hugging Face tokens, `sk-` keys, AWS access keys, private key blocks, service account JSON, Slack tokens and bearer literals. None matched.
- Quoted password, secret and token assignments: four matches. Three are constants in test files (`tests/redteam/conftest.py`, `tests/investigations/conftest.py`, `tests/mcp/tools/test_trace_evidence.py`). The fourth is new since Session 6: `PASSWORD_ENV = "RED_TEAM_RUN_PASSWORD"` in `finsentry/redteam/run_gate.py`, which is the name of the variable and not a value. None equals the real run password.
- File names: no `.env`, key, certificate, credential or `.vercel` file is tracked or was ever committed. `.gitignore` covers `.env`, `.env.*.local`, `*.pem`, `*.key` and `.vercel/`.
- The built output (`web/.next/static`, `web/.next/server`, `web/public`, 371 files): neither value is present, and the only `NEXT_PUBLIC_` name is `NEXT_PUBLIC_GATEWAY_URL`.

What it does not cover:

- Binary files in history, such as the screenshots. The scan reads text diffs only.
- A secret that matches none of the shapes above. There is no entropy check.
- Anything outside this repository, such as the Google Cloud project settings.

The scan was written for this repository and is not a replacement for a dedicated scanner. Run `gitleaks detect` or `trufflehog git` once before flipping the visibility.

Two exposures that are not credentials, for you to decide:

1. All 413 commits carry the address in your git `user.email` as both author and committer. A public repository shows it, and changing it means rewriting history. GitHub offers a `users.noreply.github.com` address for future commits, but it does not change the old ones.
2. Four commits contain `EDGAR_IDENTITY=fin-sentry noreply@fin-sentry.local`. It is a placeholder, not a personal address. `.env.example` no longer carries any value.

If a real credential is ever found, the steps are: rotate it at the provider first, then remove it from history with `git filter-repo` or BFG, then force-push and ask collaborators to re-clone. Rotation and the rewrite are irreversible, so neither was done.

## Environment and Vercel settings

`.env.example` lists every key the code reads, 32 in all, with no values. The gateway, consumers and dashboard read the backend keys from their own environment, never from Vercel.

| Vercel setting | Value | Status |
|---|---|---|
| Framework preset | Next.js | config-ready |
| Root directory | `web` | config-ready |
| Install command | `npm ci` | config-ready: `web/package-lock.json` is tracked. `npm ci` itself was not run in Session 8 |
| Build command | `npm run build` | tested locally: passes, 12 route entries |
| Output directory | the default, `.next` | config-ready |
| Node.js version | 20.x (`web/package.json` sets `engines.node` to `>=20.9.0`) | tested locally on Node 20.20.2 |
| Environment variable names | `NEXT_PUBLIC_GATEWAY_URL` only | config-ready: it is the only `NEXT_PUBLIC_` name in the built output |

Do not set `RED_TEAM_RUN_PASSWORD` on Vercel. It belongs to the gateway host, and the browser sends what a visitor types in the `X-Run-Password` header to the gateway. No `vercel.json` is needed.

### How the gateway URL is used

`web/lib/config.ts` has two modes, chosen at build time.

- **`NEXT_PUBLIC_GATEWAY_URL` unset.** The browser calls its own origin at `/ops/*`, and `next.config.ts` rewrites that to `http://localhost:8000`. On Vercel that target does not exist, so each data page renders its unavailable state. No CORS is involved.
- **`NEXT_PUBLIC_GATEWAY_URL` set.** Server components fetch from that URL, and the browser calls it directly, bypassing the rewrite. The gateway then needs these changes before it works from a Vercel origin:
  - **CORS:** the allowlist in `finsentry/gateway/main.py` is fixed to `http://localhost:3000`. It must name the production Vercel origin, and every preview origin if previews should work. Methods `GET` and `POST` and `allow_headers=["*"]` are set so the `X-Run-Password` preflight should pass. That is untested.
  - **HTTPS:** a page served from Vercel is HTTPS, so the gateway must be HTTPS as well. A browser blocks an `EventSource` or `fetch` to a plain `http://` gateway as mixed content.
  - **A gate on every route that spends:** the run password covers the Red Team run and the Agent start. A public gateway should not expose anything else that costs money.

## Readiness by tier

**Config-ready**

- `.env.example` keys, `engines.node`, the build command and output, ignored env and `.vercel` files, the tracked lockfile.
- `next.config.ts` rewrites `/ops/*` to the gateway. `compress: false` is only needed locally, and Vercel compresses at its edge.
- The Live Operations capture on the homepage is `operations-day12-s8.png`. The Next image optimizer sends `Cache-Control: public, max-age=14400`, so a browser keeps a replaced file for up to four hours under the same name. Any recapture must use a new filename.

**Dependency still needs hosting**

- The gateway: FastAPI with Prompt Guard, Llama Guard, Presidio and the rails, the SSE stream and the read routes.
- Postgres with pgvector, Redpanda, RisingWave and the dashboard (metrics) service.
- The downstream answer model on Ollama, and the flash and frontier consumers that call Gemini.
- None of these has a free hosted form that keeps the $0 rule, and a hosted gateway would also need the CORS and HTTPS changes above and a public gate in front of every route that spends.

**Behavior actually tested (Session 8, local stack)**

- `npm run build` passes: 12 route entries, 6 static (`/`, `/_not-found`, `/architecture`, `/investigations`, `/judges`, `/red-team`) and 5 rendered on demand (`/agent`, `/agent/[id]`, `/generation`, `/operations`, `/overview`).
- Playwright, 274 tests against the dev server: 271 passed, 3 skipped (the existing disagreement-trace skips), none failed. An earlier run of 273 tests against the production build (`next start`) gave 270 passed and 3 skipped.
- The homepage on the production build loads `operations-day12-s8.png` through the image optimizer, at the natural size of the new file.
- `/` and `/operations` at 375, 768, 1024 and 1440 pixels: no horizontal overflow and no console error.
- pytest: 1536 passed, 4 skipped. Vitest: 179 passed. tsc, eslint, prettier, ruff and mypy are clean.
- With the stream blocked in the browser, Live Operations states that evaluation telemetry is unavailable (Playwright). The Agent start form renders as an unavailable notice with no form when the gateway did not answer (a unit test of the component, not a real outage).
- The secret scan and the built-output scan above.

**Needs a check on a deployed host (not tested)**

- Any request on a Vercel host.
- The rewrite to a remote gateway.
- CORS from a Vercel origin, including the preflight for `X-Run-Password`.
- SSE from a browser on an HTTPS origin to an HTTPS gateway.
- Every server-rendered page with the gateway unreachable. Only the two states named above were tested, one by blocking the stream and one by rendering the component. A whole page rendered on Vercel with `localhost:8000` refusing connections was not.
- `npm ci` on Vercel's build image.

## What renders without the live gateway

| Route | Rendering | Source | With no gateway |
|---|---|---|---|
| `/` | static | committed `lib/demo-record.json` and `public/screenshots` | complete |
| `/architecture` | static | committed static content | complete |
| `/overview`, `/generation`, `/agent`, `/agent/[id]`, `/operations` | on demand | the gateway, read on the server | each section states that it is unavailable |
| `/investigations`, `/red-team` | static shell | the gateway, read in the browser | unavailable states |
| `/judges` | static | redirects to `/investigations` | follows the redirect |

With archived-evidence mode on, every row above except `/` and `/architecture` shows archived records instead (see the section below).

The routes that start work are the Red Team run button and the Agent start form. Both post to the gateway behind the run password, and the gateway refuses them when it has no password set. With no gateway reachable they cannot spend anything.

## Archived-evidence mode (Session 9)

The site can now serve a read-only copy of the committed archive, so a deployed frontend shows real records and not unavailable pages. It is switched on by one explicit build value, `NEXT_PUBLIC_ARCHIVE_MODE=true`. A failed gateway call never turns it on, so a real outage cannot pass for an archived session. With the value unset the behavior is exactly the live behavior above.

What the mode does:

- The `/ops` rewrite to the gateway is switched off. Server components read the archive in process (`lib/ops-fetch-server.ts`) and the browser asks this site's own `/api/archive/*` route handler (`lib/ops-fetch.ts`). Nothing is sent to a gateway, and the route handler exports `GET` only.
- One fixed line sits under the top bar on every archived page: "Archived evidence. This is a recorded copy of real runs, not a live system. Every record keeps its original time." The landing and Architecture pages are static and do not carry it.
- Every control that starts work is off: the Red Team run workflow, the Agent start form and "Investigate this". None of them makes a request.
- Live Operations has no stream. It reads one archived snapshot, rebuilt from the archived records with the view definitions in `infra/risingwave/init.sql`, with the original one-minute windows and every section marked stale.

Where each route comes from:

| Route | Archive source | Contract check |
|---|---|---|
| `GET /ops/traces`, `/ops/traces/{id}` | `stream/rag-responses`, `judge-verdicts`, `rag-frontier-verdicts` | Same response as the gateway for 333 trace details and 11 list queries |
| `GET /ops/investigations`, `/ops/investigations/{id}` | `postgres/investigations`, `investigation_events` | Same response for the list and all 7 details |
| `GET /ops/redteam/scenarios`, `runs`, `runs/{id}`, `executions`, `executions/{id}` | `postgres/red_team_*`, `finsentry/redteam/scenarios.yml` | Same response for the registry, 27 runs and 43 executions |
| `GET /ops/calibration/health` | `docs/measurements/reliability/canary-live-smoke-d6p2.json` and a copy of the drift policy | Same response |
| `GET /ops/metrics/snapshot` (archive only) | the three stream files, re-aggregated | Rebuilt, not copied. Checked against an independent computation |
| `GET /ops/redteam/run-gate` | none | Answers `runs_enabled: false`, a fact about the mode |
| `GET /ops/gateway-probe/latest` | none | **Not in the archive.** The page says the probe is not part of the archived evidence |

The contract checks compared the live gateway with the archive route on the same data, response by response, with zero differences. The Red Team and Agent responses were also compared with the real pydantic models.

Gaps to know about:

- The recorded gateway probe lives in the `gateway_probe_runs` table, which the archive does not export, so Live Operations shows no probe figure in this mode. Adding it means extending the archive export, which is an operator decision.
- No flash and frontier disagreement trace exists in the archive, because the Amazon trace expired from the topics. Overview and Investigations show none, which is the stored truth. The landing page keeps its committed capture.
- The snapshot's frontier group sums the fifteen minutes before the newest archived frontier bucket, because the live rule counts back from the current time and the archive has no current time.
- A few error strings still say "the gateway". They appear only when an archive file cannot be read.

### Bundling

Six functions read the archive or ask for it: `/overview`, `/operations`, `/generation`, `/agent`, `/agent/[id]` and `/api/archive/[...path]`. `next.config.ts` traces the repository root in this mode and lists each file by path. Because every module that can reach the file readers is traced with all nine paths, each page excludes the groups it does not read. The built `.nft.json` files show the result:

| Function | Archive files it carries |
|---|---|
| `/api/archive/[...path]` | all nine (3.4 MB: 3.3 MB of stream records, 0.14 MB of tables, the canary artifact and `scenarios.yml`) |
| `/overview`, `/operations` | the three stream files and the canary artifact |
| `/generation` | the three stream files |
| `/agent` | `investigations.jsonl` |
| `/agent/[id]` | none, it asks the route handler |

The total is far below Vercel's function size limit. The build stops with a clear error when `docs/demo-archive` is not next to `web/`, because a build that cannot see the files would ship pages that all say unavailable.

### Deploy steps

1. Run `gitleaks detect` or `trufflehog git` on the repository, and decide the author-email question above. Then push and make the repository public.
2. Create the Vercel project with Root Directory `web`, and turn on "Include source files outside of the Root Directory in the Build Step". The archive and the registry sit outside `web/`.
3. Set `NEXT_PUBLIC_ARCHIVE_MODE=true`. Leave `NEXT_PUBLIC_GATEWAY_URL` unset. Do not set `RED_TEAM_RUN_PASSWORD`.
4. Deploy with the default build command, `npm run build`.
5. Smoke test on the deployed host (below).

### What a local build does not prove

A local production build proves the route list, the tracing of each function and the behavior against `next start`. It does not prove file tracing, function size or the route handler on Vercel's build image and runtime. After the first deploy, check:

- `/api/archive/traces?limit=1` returns the newest trace `b357b1c2-804d-43ef-8b1d-7f1eb5f01287`.
- `/api/archive/redteam/scenarios` returns 10 scenarios, and `/api/archive/investigations` returns 7.
- `/overview` shows 291 executions and `/agent/43751b14-b080-4f5b-8391-33b914f12f22` shows its hypotheses.
- `POST /api/archive/redteam/runs` answers 405.
- The deployed pages show the archive line and make no request to another origin.

If a page says a record could not be read after deploy, the files were not traced into that function. Check the setting in step 2 first.

## Recommended public-demo path

Hosting the gateway is not an option at $0, so the recommended path is archived-evidence mode above. Deploy the frontend with the mode on, smoke-test it, then write the README. The earlier plan to deploy the frontend alone with every data page unavailable is superseded.

## Data caveat: settled in Day 12 Session 7

The pytest regression probes are test traffic. 117 of the 325 archived `rag-responses` events and 42 of the 333 traces the UI read had a query of the exact shape "duplicate-verdict regression probe" followed by one trace id. The UI trace list now leaves that shape out, so Overview, Investigations and Live Operations count 291 traces. The stored rows and the archive are unchanged, a probe trace still opens by its id, and the query function the MCP tools share still returns every row. The filter is a prefix plus a 36 character length match, not a UUID check, and that is deliberate. The throughput history and its 100 ms buckets are no longer shown anywhere.
