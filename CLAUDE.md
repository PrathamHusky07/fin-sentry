# Project 4 — AI Reliability and Evaluation Platform

This CLAUDE.md is loaded every session. It defines how you work on this project. Follow it exactly. When the instructions here conflict with a general habit you have, these instructions win.

The full design specification lives at `docs/internal/Project4_Description.docx`. Read it once at the start of any new session and refer back to it whenever you are unsure why something was decided. It is the source of truth for what we are building. If something in the code conflicts with the spec, the spec is right unless we have explicitly agreed to change it.

## What this project is

An AI Reliability and Evaluation Platform that sits in front of any RAG or LLM endpoint. It applies defense-in-depth guardrails on inputs, retrieval, and outputs. It streams every interaction through a real-time evaluation pipeline where a two-tier judge layer scores quality and factuality. It calibrates the judges against a human-labeled financial golden set. It exposes its operational state through an OpenTelemetry-instrumented MCP server. The demo domain is financial RAG over SEC EDGAR filings for ten specific companies. The eleven-day build plan is in the description document.

This is a portfolio project for a candidate interviewing for Senior AI Engineer, AI Platform Engineer, and Forward Deployed Engineer roles. Every decision optimizes for two things. One, a hiring manager reading the README respecting the code under the hood. Two, the candidate defending every design choice in a technical interview against a senior interviewer. This is not a hobby project and it is not a tutorial.

## Stack (fixed, do not substitute)

- Backend gateway: FastAPI, NeMo Guardrails, Llama Prompt Guard 2 86M, Presidio, Llama Guard 3 8B quantized, Guardrails AI, tenacity for retries, Docker.
- Streaming: Redpanda, RisingWave, Postgres. Docker Compose for local orchestration.
- Judges: Gemini 2.5 Flash for the flash tier through the Google Cloud free-tier credit. HHEM-2.1-open, Patronus Lynx 8B, and Prometheus 2 7B for the frontier tier, all local via Hugging Face.
- Datasets: FinanceBench, FinQA-hallucination-detection, live SEC EDGAR filings via edgartools for the ten-company demo corpus.
- Observability and MCP: OpenTelemetry Python SDK, official MCP Python SDK, LangSmith free tier for judge tracing.
- Frontend: React 19.2, Next.js 16 with the App Router, TypeScript in strict mode, Tailwind CSS, Recharts, Server-Sent Events.
- Deployment: Cloud Run for the deployed gateway, Vercel for the deployed frontend. All within free tiers.
- Development: Claude Code Max, which the user already subscribes to.

If you want to reach for anything else, ask first. The reason a specific library was chosen is written in the spec.

## Model policy

Default model is `claude-sonnet-4-6`. Escalate to Opus via `/model opus` only for architecture planning, multi-file refactors, integration debugging that has already resisted one Sonnet attempt, or the calibration and normalization math where a subtle bug is expensive. Drop to Haiku via `/model haiku` for mechanical work: file renames, README edits, dependency version bumps, adding docstrings to functions that already work, running formatters, and translating checked-in output data into a chart script.

Do not run the entire session on Opus. It burns budget for no gain on tasks Sonnet handles cleanly. Do not run the whole session on Haiku either. It saves tokens on work that then needs to be redone. Match the tool to the task.

When starting a new day, name the model you are on and why in the first response of the session. That gives us both a checkpoint.

## Commands (exact)

Backend Python (from `platform/`):

- Dev server: `uvicorn platform.gateway.main:app --reload --port 8000`
- Docker Compose stack: `docker compose -f docker-compose.dev.yml up -d`
- Test: `pytest -x -q`
- Lint: `ruff check .`
- Format: `ruff format .`
- Type check: `mypy platform/`

Frontend (from `web/`):

- Dev: `npm run dev`
- Build: `npm run build`
- Type check: `npx tsc --noEmit`
- Lint: `npm run lint`
- Format: `npx prettier --write .`

Run the type check, the lint, and the tests before saying a change is done. A working dev server is not evidence the build passes. If a change touches both the backend and the frontend, run both sets of checks. Do not report success on a partial run.

## The four principles you follow

### One. Think before coding.

Do not make assumptions on my behalf and run with them. If a task is ambiguous, tell me what you think the two or three reasonable interpretations are and ask which one I want. If you notice something in my request that does not match what the description doc says, surface the mismatch before you start writing code. If you are about to make a design decision I have not explicitly signed off on, name it and wait.

State assumptions explicitly at the top of any non-trivial change. If a simpler approach exists than the one I asked for, say so before writing the more complicated one.

Before implementing anything beyond a one-line change, state the plan in three to six bullets and wait for confirmation. If a decision has a real tradeoff, present both options briefly, recommend one, and proceed after I confirm.

### Two. Simplicity first.

Write the minimum code that solves the problem. No features I did not ask for. No abstractions for single-use code. No configurability I did not request. No error handling for scenarios that cannot happen.

Every function should be either short and obvious or medium and well-named. If you are writing a class with more than five methods, ask whether it should be two classes. If a file passes three hundred lines during a single day of work, ask whether it should be split.

If two hundred lines could be fifty, rewrite them.

### Three. Surgical changes.

Touch only what the current task requires. Do not "improve" adjacent code, refactor unrelated files, or reformat things because they look untidy. Match the existing style of any file you edit even if you would write it differently.

If you notice unrelated dead code or a real problem in a nearby file, tell me about it in your reply. Do not delete it or fix it in the same commit.

When your changes leave imports, variables, or functions unused, remove those specific orphans. Do not remove pre-existing dead code unless I ask.

Every changed line in a diff should trace directly to a task I gave you or a bug that task uncovered.

### Four. Goal-driven execution with verification.

Transform every task from "do X" into "make this test pass" or "make this observable behavior true." Before implementing, state the success criterion in one sentence. When the task involves adding a rail, a judge, or an experiment, the success criterion is a runnable check, not a claim.

For any multi-step task, write a short numbered plan first. For each step, name the verification.

```
1. Ingest FinanceBench golden set → verify: 150 rows load into Postgres with schema matching spec
2. Wire up the RAGAS Faithfulness scorer → verify: given a canned (question, context, answer), returns expected score
3. Attach it as the retrieval rail → verify: trace event includes faithfulness_score field
```

Loop until every verification passes. When you are done, run the verification steps yourself before telling me it is complete.

## Prose discipline (no AI-generated tells)

This applies to every commit message, every README paragraph, every code comment that ships, and every string that appears in the frontend or in a trace message a user or interviewer will read.

- No em-dashes in body copy. Use periods or commas instead. Em-dashes in code comments about internal machinery are acceptable but not in user-facing text.
- No "It's not just X, it's Y" constructions.
- No banned words: delve, delving, tapestry, landscape (as metaphor), robust, leverage, streamline, empower, seamless, cutting-edge, best-in-class, world-class, revolutionize, unlock (as verb metaphor). These are AI tells and they will discredit the whole document to a senior reader in the first paragraph.
- No sentence openers: Moreover, Furthermore, Additionally, In today's, In the modern era.
- No balanced tricolons ("X, Y, and Z" three times in the same paragraph). One is fine, more reads as AI cadence.
- No hedging language: perhaps, arguably, in many ways, one could say, it can be argued that.
- Prefer short declarative sentences. If a sentence has three commas, it probably needs to become two sentences.
- When you are about to write an em-dash, ask whether a period would work. Usually yes.

When you finish writing any prose destined to ship, re-read it and check it against this list before saving.

## Project-specific rules that override any general habit

### Zero paid APIs in the critical path.

Gemini 2.5 Flash runs through the Google Cloud free-tier credit. Everything else is open source and runs locally. If you find yourself about to import an SDK for a paid service that is not Gemini, stop and ask. If a library you want to use has a paid tier that its free tier does not fully cover for this project's usage pattern, stop and ask.

### The description document is the spec.

The description doc at `docs/internal/Project4_Description.docx` defines the architecture, the four components, the three experiments, the datasets, the tech stack, and the eleven-day build order. Do not deviate from it without asking. If you think something in the spec is wrong, say so and wait for my call before changing course.

### One agent lives elsewhere. This project has no agents.

There is no LangGraph in this codebase. No CrewAI. No AutoGen. The gateway is a request-response pipeline. The judges are LLM calls, not agents. The MCP server is a data-serving interface. If you catch yourself scaffolding an agent, you have misunderstood the project. Stop and re-read the spec.

### Follow the day plan in order.

The description doc has an eleven-day plan. Each day builds on the last. Do not jump ahead. Do not skip verification of the previous day's work when starting the next day. At the start of each day, restate the goals for that day in one paragraph and confirm with me before writing code.

### Verification is deterministic. Judges are not verification.

Judge scores tell us about response quality. They are not test results. When you write tests for the platform's own code, use pytest for Python and vitest for TypeScript. Do not use an LLM to grade whether the code works. Tests are deterministic. Judges are calibrated but stochastic. The two are different tools for different jobs.

### Commit hygiene.

Commit at the end of every logical unit of work, not once at end of day. Commit messages are imperative and short. `add gateway input rails behind NeMo Guardrails` not `feat: implemented the input rails for the guardrails feature (WIP)`. Every commit should build and run its tests. If you have to commit broken code to save your place, prefix the message with `wip:` and open the next session with fixing it.

Never include AI-attribution in commit messages. No `Co-authored-by: Claude`. No robot emoji footer. No "generated with Claude Code" line. A hiring manager scrolling the commit history and seeing those lines assumes the candidate did not write the code themselves. Every commit reads as authored by the human developer, because that is the honest signal. The developer decided what to build, decided when it was done, and accepted responsibility for shipping it.

### Type discipline.

TypeScript is in strict mode. Python is fully type-hinted at every function boundary. No `any` in TypeScript. If a type is genuinely unknown, use `unknown` and narrow. No `Any` from `typing` in Python without a comment explaining why the escape hatch was necessary.

### Responsive matters where the frontend is user-facing.

The three dashboard routes render on desktop for the interview walkthrough and should stay usable on mobile because a hiring manager may open the live demo link from their phone. Mobile-first Tailwind, tap targets at least 44 by 44 pixels, text at least 16 pixels on mobile. Verify at 375, 768, and 1440 widths before saying a frontend change is done.

## When to invoke the skills in `.claude/skills/`

Three skills live in this repo. Each triggers on a specific kind of work.

- **`guardrails-integration`** — read and follow when you are adding a new rail to the gateway, modifying an existing rail's fail-open versus fail-closed behavior, or touching how the rail stack emits trace events.
- **`judge-scoring`** — read and follow when you are adding a judge to either tier, modifying the bias mitigations, wiring up FaithJudge peer retrieval, or changing the ensemble normalization.
- **`experiment-writeup`** — read and follow when you are running one of the three experiments (load test on Day 10, cost-versus-accuracy sweep on Day 10, reliability-under-failure on Day 9) or the Cohen's kappa threshold sweep on Day 6.

Read the SKILL.md at the top of the relevant directory before doing the work. It tells you the pattern and the verification.

## When to ask me instead of guessing

Ask before you:

- Add a new dependency the spec does not name.
- Change a public API surface (route, MCP tool name, event schema).
- Merge two components that the spec keeps separate.
- Skip a rail, a judge, or an experiment described in the spec.
- Deploy anything to Cloud Run or Vercel.
- Push a commit that touches more than three files unless the task obviously requires it.
- Introduce a new configuration file or a new environment variable.

Do not ask before you:

- Fix a typo in your own comment.
- Add a small utility function used only inside the file you are already editing.
- Change an internal variable name for clarity.
- Add a missing test.

When in doubt, ask. A five-second question saves an hour of unwinding.

## Definition of done for any change

1. All exact commands from the Commands section that apply to the changed files pass with zero warnings. Backend changes run pytest, ruff check, ruff format, mypy. Frontend changes run npm run build, tsc, lint, prettier.
2. Any new code has tests. Tests are meaningful. A test that asserts the code compiled is not a test.
3. If the change touches a rail, the guardrails-integration verification checklist passes.
4. If the change touches a judge, the judge-scoring verification checklist passes.
5. If the change produced a number that goes into the README, the experiment-writeup verification checklist passes.
6. If the change affected the frontend, it was verified at 375, 768, and 1440 widths in the browser.
7. No console errors or warnings in the browser during frontend verification.
8. The commit message follows the commit hygiene rules and has no AI-attribution footer.
9. The description doc has not been contradicted. If the change deliberately diverged from the doc, the doc gets a matching update in the same commit.

## Do not

- Do not add features not requested. No dark mode toggle. No i18n. No CMS. No auth flows beyond the API-key auth for the deployed demo on Day 11. No user accounts. No admin panel.
- Do not install a UI kit that bundles more than what is used.
- Do not add state management libraries. The frontend does not need Redux, Zustand, or Jotai for this scope.
- Do not touch `docs/internal/`. That is the private planning material.
- Do not commit `.env*`, `.vercel/`, `node_modules/`, virtual environments, `.claude/settings.local.json`, dataset files, or experiment output data.
- Do not add AI-attribution to commit messages.
- Do not use `any` in TypeScript.
- Do not use `<img>` in the frontend. Use `next/image`.
- Do not host a resume PDF or personal contact information on the deployed frontend.
- Do not add an alerting integration (PagerDuty, OpsGenie, Slack webhooks). Judge drift alerts surface in the dashboard only.
- Do not add a retraining loop for the judges. The spec's fine-tuning discussion is a future direction, not part of this build.
- Do not add any dataset beyond the three in the spec.
- Do not add any company beyond the ten listed for the SEC EDGAR corpus.

If I ask for one of these mid-build, remind me they are out of scope and confirm before adding.

## Working style

- Before implementing anything beyond a one-line change, state the plan in three to six bullets and wait for confirmation.
- Prefer editing existing files over creating new ones. Do not create a new module when an existing one can take a parameter.
- When a decision has a real tradeoff, present both options briefly, recommend one, and proceed after I confirm.
- If you catch yourself writing more than two hundred lines for a single component or module, stop and split.
- End of each build day, produce a one-paragraph summary of what got built, what got skipped, and what needs to happen first thing tomorrow. Update `docs/internal/build-log.md` with one dated entry per day. Keep it short.
