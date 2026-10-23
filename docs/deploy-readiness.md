# Deploy readiness

Written at the end of Day 12 Session 6. Nothing is deployed. The Next.js frontend builds and the checks below passed on the local stack. The gateway, Postgres, Redpanda, RisingWave and the local model do not run on Vercel and are not hosted anywhere.

## Release gate: secret audit

**Result: no secret found in the paths and history scanned.** That is a narrower claim than "safe to publish", and the limits are listed below.

What was scanned, on 2026-10-22, before the repository goes public:

- The working tree and every commit on every ref (396 commits, one branch, no stash).
- The exact values of `RED_TEAM_RUN_PASSWORD`, `HF_TOKEN`, `EDGAR_IDENTITY` and the two database URLs from the local `.env`, searched in the tree and with a history pickaxe. The password and the token appear nowhere. The database URLs are the local `postgres:postgres` defaults.
- Token shapes across all added lines in history: Google API keys, GitHub tokens, Hugging Face tokens, `sk-` keys, AWS access keys, private key blocks, service account JSON, Slack tokens and bearer literals. None matched.
- Quoted password, secret and token assignments. Three commits matched, and all three are constants in test files (`tests/redteam/conftest.py`, `tests/investigations/conftest.py`, `tests/mcp/tools/test_trace_evidence.py`). They are test literals and none equals the real run password.
- File names: no `.env`, key, certificate, credential or `.vercel` file is tracked or was ever committed. `.gitignore` covers `.env`, `.env.*.local`, `*.pem`, `*.key` and `.vercel/`.
- The built output (`web/.next/static`, `web/.next/server`, `web/public`): none of the values above is present, no server-only variable is read, and the only `NEXT_PUBLIC_` name is `NEXT_PUBLIC_GATEWAY_URL`.

What it does not cover: binary files in history (screenshots), a secret that matches none of the shapes above, and anything outside this repository, such as the Google Cloud project settings. The scan was written for this repository and is not a replacement for a dedicated scanner. Run `gitleaks detect` or `trufflehog git` once more before flipping the visibility, if you have either.

Two exposures that are not credentials, for you to decide:

1. Every commit carries the author and committer address `prathamesh.kulkarni2398@gmail.com`. A public repository shows it. Changing it means rewriting history.
2. Three early commits contain `EDGAR_IDENTITY=fin-sentry noreply@fin-sentry.local` in `.env.example`. It is a placeholder, not a personal address. `.env.example` no longer carries any value.

If a real credential is ever found, the steps are: rotate it at the provider first, then remove it from history with `git filter-repo` or BFG, then force-push and ask collaborators to re-clone. Rotation and the rewrite are irreversible, so neither was done here.

## Environment and Vercel settings

`.env.example` lists every key the code reads, 32 in all, with no values. The gateway, consumers and dashboard read the backend keys from their own environment, never from Vercel.

| Vercel setting | Value |
|---|---|
| Framework preset | Next.js |
| Root directory | `web` |
| Install command | `npm ci` |
| Build command | `npm run build` |
| Output directory | the default, `.next` |
| Node.js version | 20.x (`web/package.json` sets `engines.node` to `>=20.9.0`) |
| Environment variable names | `NEXT_PUBLIC_GATEWAY_URL` only |

Do not set `RED_TEAM_RUN_PASSWORD` on Vercel. It belongs to the gateway host, and the browser sends what a visitor types in the `X-Run-Password` header to the gateway.

`NEXT_PUBLIC_GATEWAY_URL` is read at build time. Once it is set, server components fetch from that URL and the browser calls it directly, so the gateway must allow the Vercel origin. Its CORS list is fixed to `http://localhost:3000` in `finsentry/gateway/main.py`. Left unset, the deployed server tries `http://localhost:8000`, finds nothing and renders each data page's unavailable state.

## Readiness by tier

**Config-ready**

- `.env.example` keys, `engines.node`, the build command and output, ignored env and `.vercel` files.
- `next.config.ts` rewrites `/ops/*` to the gateway. `compress: false` is only needed locally, and Vercel compresses at its edge.
- No `vercel.json` is needed. The defaults above are the whole configuration.

**Dependency still needs hosting**

- The gateway: FastAPI with Prompt Guard, Llama Guard, Presidio and the rails, the SSE stream and the read routes.
- Postgres with pgvector, Redpanda, RisingWave and the dashboard (metrics) service.
- The downstream answer model on Ollama, and the flash and frontier consumers that call Gemini.
- None of these has a free hosted form that keeps the $0 rule, and a hosted gateway would also need a CORS change and a public gate in front of every route that spends.

**Behavior actually tested**

- `npm run build` passes: 11 routes, 6 static and 5 rendered on demand.
- The Playwright suite against the local stack, the pytest suite, type and lint checks, and the recovery rehearsal in disposable databases.
- The secret scan and the built-output scan above.
- Not tested: any request on a deployed Vercel host, the rewrite to a remote gateway, CORS from a Vercel origin, SSE through Vercel's edge, and a deployed page with the gateway unreachable.

## What renders without the live gateway

| Route | Source | With no gateway |
|---|---|---|
| `/` | committed `lib/demo-record.json` and `public/screenshots` | complete |
| `/architecture` | committed static content | complete |
| `/overview`, `/generation`, `/agent`, `/agent/[id]`, `/operations` | the gateway, read on the server | each section states that it is unavailable |
| `/investigations`, `/red-team` | the gateway, read in the browser | unavailable states |
| `/judges` | redirects to `/investigations` | follows the redirect |

The routes that start work are the Red Team run button and the Agent start form. Both post to the gateway behind the run password, and the gateway refuses them when it has no password set. With no gateway reachable they cannot spend anything.

## Recommended public-demo path

Recommendation: **a scoped demo mode backed by the real archived records**, reached in two steps. Hosting the gateway is not an option at $0.

1. **Deploy the frontend alone now.** It costs nothing and needs no code. Landing and Architecture are complete. The data pages say they are unavailable. This proves the Vercel build and domain, and it is honest, but a visitor sees mostly unavailable states.
2. **Add an archived-evidence mode in the next session.** The archive in `docs/demo-archive` already holds the stream records, the Red Team runs and the Agent investigations. The steps:
   1. Serve the read-only subset of `/ops/*` from Next route handlers that read the bundled archive files, with `outputFileTracingIncludes` so the files ship with the function.
   2. Switch the `/ops/*` rewrite off in that mode, so nothing leaves Vercel.
   3. Mark every page with one fixed line saying the data is archived evidence and not a live system.
   4. Red Team run and Agent start controls: already unavailable when the gateway does not answer (Day 12 Session 7). Nothing is left to do here except check it on the deployed host.
   5. On Live Operations, serve the archived evaluation telemetry and keep the recorded probe, each with its own date. The status strip is now four informational items, so it needs no change. The stored request buckets and their charts were removed from the page in Session 7, so there is nothing to carry over for them.

Step 2 is a session of work and was not started here.

## Data caveat: settled in Day 12 Session 7

The pytest regression probes are test traffic. 117 of the 325 archived `rag-responses` events and 42 of the 333 traces the UI read had a query of the exact shape "duplicate-verdict regression probe" followed by one trace id. The UI trace list now leaves that shape out, so Overview, Investigations and Live Operations count 291 traces. The stored rows and the archive are unchanged, a probe trace still opens by its id, and the query function the MCP tools share still returns every row. The throughput history and its 100 ms buckets are no longer shown anywhere.
