@AGENTS.md

# Fin-Sentry Frontend

This file governs two distinct surfaces. Read the section that applies before touching either one.

**The application** (`/operations`, `/judges`, `/red-team`, and anything else that queries real platform data) is an AI reliability and evaluation **operations tool**, not a SaaS product, not a landing page, not a generic admin-template dashboard, not a shadcn component showcase, and not a university project. It is built to be read by a hiring manager and defended in an interview. Every screen should look like something an on-call engineer would actually use during an incident, not something demoing a component library.

**The presentation layer** (the project landing experience, built separately from the application) explains and showcases the engineering work. It is a project presentation, not a commercial product site. See "The presentation layer" section below for its specific rules. The presentation layer is built: the landing route (`/`) and the architecture route (`/architecture`). Its rules below keep governing any change to them.

Read the root `../CLAUDE.md` first — it governs the whole project (the four principles, prose discipline, zero-spend rule, day-plan discipline). This file adds frontend-specific rules on top of it; it does not replace it.

## Information architecture (application only)

Order every screen signal → investigation → provenance → evidence. A viewer should see "is something wrong" before "here are some charts." Status and failure state sit at the top of the page, not buried in a card grid. Drill-downs (modals, detail panes) come after the summary, never instead of it.

Do not build, anywhere in the application surface:

- A hero section, a feature grid, or marketing copy.
- A sidebar-plus-cards admin template that could belong to any SaaS product.
- A component purely to demonstrate a library's capabilities.

These three are explicitly allowed, and expected, on the presentation layer — see below. The prohibition is scoped to the application surface, not the whole frontend.

## Data provenance — the load-bearing rule

Every piece of data a screen renders must be traceable to exactly one of:

- `PERSISTED` — a real stored field, queryable right now.
- `DERIVED` — computed from persisted data, not stored as-is (document the derivation).
- `LIVE` — arriving via the SSE snapshot-relay (see below).
- `HISTORICAL` — real but not current; a past snapshot or artifact, labeled with its age.
- `PLANNED` — described in the product spec, not built yet.
- `NOT_AVAILABLE` — described in the spec, but the backend does not and cannot currently persist it.

**Never fabricate anything in the last two categories.** Chain-of-thought reasoning, evidence spans beyond what a judge's `evidence` field actually contains, unsupported-claim details, a per-model dissent breakdown when only one real judge ran, P50/P99 latency when only P95 is computed, by-endpoint or by-rail breakdowns with no backing query — none of these exist until a specific backend field does. When a UI element has no backend field behind it, omit the element or render an explicit "not persisted" state. Do not render a placeholder that could be mistaken for real data.

## Judge / frontier data — specific and non-negotiable

The live `rag_frontier_verdicts.per_judge_results` array mixes real judge rows and leftover stub rows from earlier calibration runs. When rendering it:

- Identify every judge by its `judge_id` field. **Never** by array position or index.
- Render only entries with a real, non-null `evidence` object. Skip `stub-a`, `stub-b`, or any entry with `evidence: null` silently — do not render them as if they were real judges with nothing to show.
- Label results as coming from one judge (`gemini-rubric`, as of Day 8). **Never** imply a three-model ensemble (HHEM, Lynx, Prometheus) is live — Lynx and Prometheus have no adapter in this codebase, and HHEM is disabled by default.

If a future backend change adds real multi-judge rows, update this section and the provenance rules that depend on it — don't let this note silently go stale.

## SSE semantics

The gateway's SSE route relays periodic **snapshots** of the latest known metrics state. It is not an event log and not a push from RisingWave — RisingWave never pushes; the backend polls it. Build the client accordingly:

- Treat each `snapshot` event as the full current state, not a delta.
- Surface staleness. The snapshot payload carries a `stale` flag per section — show it (a muted/dimmed state, an "as of" timestamp), never hide it behind a number that looks current.
- Reconnect silently. `EventSource` auto-reconnects on its own; don't build custom retry UI for it. A reconnect just means the next snapshot arrives a little later.
- Never simulate the feed. No `setInterval(fetch(...))` dressed up as SSE, no mock payloads, no synthetic data standing in for a real connection failure.

## Component architecture

Server Components by default. Reach for a Client Component only where interactivity or a browser API is actually required (`EventSource`, a form, a modal's open state) — mark the boundary at the smallest component that needs it, not the whole page.

No premature abstraction. Three near-identical blocks are fine as three blocks until a fourth makes the pattern obvious; don't build a generic "data card" system for two use cases.

No state-management library. `useState`/`useReducer`/Server Components cover everything this app needs. If a screen seems to need more, that's a sign the data should move server-side, not a sign to add Zustand or Redux.

## Stack (fixed — do not substitute)

Next.js 16 App Router, React 19.2, TypeScript strict (no `any` — if a type is genuinely unknown, use `unknown` and narrow), Tailwind CSS, Recharts for time series, native `EventSource` for SSE. `next/image`, never a bare `<img>`. No other UI kit, charting library, or state library without asking first, per the root CLAUDE.md's ask-before-adding rule.

## Accessibility and responsive

Tap targets at least 44×44px. Text at least 16px on mobile. Every interactive element keyboard-reachable with a visible focus state (`focus-visible`, not a removed outline). Verify every frontend change at 375px, 768px, and 1440px before calling it done — this is not optional, it's in the definition of done.

## Testing

Vitest for anything that needs a test. No LLM-graded UI tests — a test that asks a model "does this look right" is not a test. Test logic (data transforms, provenance derivation, staleness computation), not pixel output.

## The presentation layer

A project presentation surface, built separately from the application above. It explains and showcases the real engineering work so a hiring manager can go from "interesting project" to understanding what was actually built. It is not a SaaS marketing site, and the line is enforced the same way the application's truth boundary is: concretely, not by tone.

Banned, with no exception:

- Commercial-product language: "book a demo," "start free," "trusted by," customer logos, testimonials, adoption numbers, pricing, or any claim implying Fin-Sentry is a product people can buy or that it operates at a scale that was not actually demonstrated.
- Videos, anywhere. Use high-quality static screenshots of the real application, designed architecture graphics, and interactive charts backed by real data instead.
- Exaggerated or generic marketing claims ("next-generation," "revolutionary," "enterprise-grade," and the banned-word list in the root `../CLAUDE.md`'s prose discipline section apply here too).

Required:

- Honest absence stays mandatory in the application: Overview, Live Operations and Investigations keep their explicit unavailable, empty, stale and not-persisted states, and never infer "healthy" from missing data. The presentation layer is not required to carry a dedicated "what this does not do" section. It still never overstates what the platform did.
- Every sentence is a complete, intentional, business-ready sentence. No sentence fragments except deliberate UI labels (nav items, button text, badges).
- No em-dashes, matching the root `../CLAUDE.md` prose discipline rules.
- The truth boundary is absolute here too. Every number, chart, screenshot, and claim must be backed by something the platform actually did. A screenshot slot must map to a real application screen that exists at the time it ships, not a mockup standing in for one. Credibility comes from evidence ("replica failure was tested against the live nginx topology"), never from adjectives ("enterprise-grade fault tolerance").

A hero section, original visual identity, an architecture graphic, and marketing-style section flow are expected and encouraged here — they are exactly what distinguishes this surface from the application. Nothing in this section relaxes the data-provenance rule above: a presentation-layer screenshot of a real screen is real; a presentation-layer chart with invented numbers is not, regardless of which surface it appears on.

## When to stop

If you're about to invent a field, a judge, a metric breakdown, or a UI state with nothing behind it in the backend, stop and ask instead. A five-second question here is cheaper than a frontend that quietly oversells what the platform actually does. On the presentation layer, the same rule applies to screenshots and claims: if the screen or the number doesn't exist yet, don't show it as if it does.
