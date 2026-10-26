# Fin-Sentry

Fin-Sentry is an AI reliability and evaluation platform. It evaluates the answers an AI system gives, measures whether its own judges can still be trusted, and investigates failures from the evidence it has stored. The reference workload is a financial RAG system over SEC filings.

[![CI](https://img.shields.io/github/actions/workflow/status/PrathamHusky07/fin-sentry/ci.yml?branch=main&style=for-the-badge&logo=githubactions&logoColor=white&label=CI)](https://github.com/PrathamHusky07/fin-sentry/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/Python-3.13-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Next.js](https://img.shields.io/badge/Next.js-16-000000?style=for-the-badge&logo=nextdotjs&logoColor=white)](https://nextjs.org/)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://github.com/pgvector/pgvector)
[![Redpanda](https://img.shields.io/badge/Redpanda-E2401B?style=for-the-badge)](https://www.redpanda.com/)
[![RisingWave](https://img.shields.io/badge/RisingWave-1A66FF?style=for-the-badge)](https://risingwave.com/)
[![Gemini](https://img.shields.io/badge/Gemini-3.6_Flash-8E75B2?style=for-the-badge&logo=googlegemini&logoColor=white)](https://ai.google.dev/gemini-api/docs)
[![MCP](https://img.shields.io/badge/MCP-9_read--only_tools-000000?style=for-the-badge&logo=modelcontextprotocol&logoColor=white)](https://modelcontextprotocol.io/)


## The problem

A RAG system answers questions about documents. Teams usually check those answers with another model, a judge, and chart its scores. That works until the judge is wrong, and a judge that has drifted does not announce it. The charts stay green while the checks mean less.

Fin-Sentry treats the judge as something to measure. It scores answers with a judge, then scores the judge against labeled data. Agreement is Cohen's kappa. Two thresholds with hysteresis separate a healthy judge from a degraded or drifted one, so a reading that wobbles near one line does not flip the state back and forth. The reading is shown with its date.

The reference workload is a plain retrieve-then-generate pipeline over SEC filings, on llama3.1:8b. It exists so the platform has something real to guard and judge. The platform is the product.

What is on record today is one manual canary reading: kappa 0.516 on 30 unseen labeled rows, between the two thresholds (0.43 and 0.54), so the state is degraded and not drifted. The thresholds, the controller that applies them, and a gated judge that would bypass a drifted judge are built and tested. They are not wired into the running pipeline, and the canary runs by hand. The platform measures and reports how far its evaluator can be trusted. It does not yet act on that automatically.

![Overview page showing 2 failed requests, 252 of 255 delivered answers judged, and a frontier judge agreement reading of 0.516 marked degraded](docs/assets/screenshots/overview.png)


## Architecture

![Fin-Sentry architecture: a request path of gateway, input rails, retrieval, generation and output rails, followed by an evaluation and evidence plane of LLM judges, streaming evidence, evaluator calibration and the incident investigator, which reaches the evidence through an MCP server, with OpenTelemetry tracing across every stage](docs/assets/architecture.png)

**The request path.** A question arrives at `POST /v1/rag/query` on the FastAPI gateway. A second endpoint, `/v1/chat/completions`, is an OpenAI-compatible relay that runs the input rails and passes the call through, with no retrieval, output checks or event. NeMo Guardrails runs three input rails as Colang flows: Llama Prompt Guard 2 for prompt injection, Presidio for six pattern-based PII types, and Llama Guard 3 (the 1B model) for hazard categories. A rail that blocks returns a 403. A rail that errors stops the request with a 503, recorded as an error and not as a policy block. Retrieval embeds the query with bge-small-en-v1.5 and searches pgvector over 8,319 chunks of 10-K, 10-Q and 8-K filings from ten companies. Each retrieved chunk then passes its own rail for source trust, indirect prompt injection and PII, and failing chunks are dropped. Generation is one call to llama3.1:8b through Ollama, bounded by a retry budget, a circuit breaker and a 60 second deadline for the whole request. The output rails check schema and citations, regulated phrases, and faithfulness. The faithfulness check is a RAGAS-style implementation of our own: Gemini extracts claims and checks each against the retrieved context, and a score below 0.7 blocks the answer. The caller gets an answer or a named block, and the gateway publishes one event per request without waiting for it. Delivery is at most once.

**The evidence path.** Two consumers read the event topic, off the request path. The flash judge scores every delivered answer on faithfulness, answer relevance and context relevance. The rubric judge takes a deterministic sample, 1 in 10 by a hash of the trace id and 1 in 100 while consumer lag stays high, and makes one Gemini rubric call with FinanceBench question and answer pairs as peer examples. Both tiers default to the same model, `gemini-3.6-flash`, and differ in prompt, scope and sampling. Verdict labels such as `ensemble_supported` survive from a multi-judge contract. With one judge, a clear verdict is classified `single_judge`. An HHEM-2.1 adapter is implemented and disabled because it fails to load with the installed transformers version. RisingWave reads the three topics and keeps nine materialized views. A dashboard service reads the views, and the gateway polls it every three seconds and relays full-state snapshots to the browser over Server-Sent Events. Redpanda topics expire old records, so what has to outlive them is copied into Postgres and into a checksummed archive in `docs/demo-archive`, which the public demo is built from. OpenTelemetry spans cover each gateway stage, each input rail and each MCP tool call. The exporter is off by default.

**Calibration.** The labeled benchmark is the FinQA hallucination set. A canary scores unseen labeled rows with the rubric judge, kappa measures agreement with the labels, and a controller applies the two thresholds: three consecutive windows at or below 0.43 enter the drifted state, and five at or above 0.54 leave it. A gated judge stands in front of the rubric judge and would bypass it while the state is drifted. Only the canary reading is real today. The controller and the gated judge are tested but not wired into the consumers.

**Investigation.** The investigator does not query the platform's databases directly. It reaches the evidence through an MCP server that exposes it as typed tools, the same contract any MCP client uses, so it can read traces, judge scores, guardrail decisions and red-team results and nothing else. Red Team exercises the real defenses against controlled inputs and records what each one caught.

## Product walkthrough

These are images of the website.

### What it is

![Homepage with the platform description and a concept map of its parts: Guard, Retrieve, Generate, Judge, Calibrate, Agent and MCP](docs/assets/screenshots/homepage.jpg)

*The homepage states the purpose in the site's own words and maps the parts: guard, retrieve, generate, judge, calibrate, the agent, and the MCP interface.*

### One trace, end to end

![Trace drill-down for an Apple net sales question showing the answer, five retrieved chunks with one cited, the flash judge scores and the frontier rubric verdict](docs/assets/screenshots/trace-detail.png)

*A trace drill-down from the website. The question is Apple's total net sales for fiscal 2024. The answer was written by llama3.1:8b and cites one of the five retrieved chunks, shown as cited and not cited. The flash judge scored faithfulness 1.000, answer relevance 1.000 and context relevance 0.760. The frontier tier was sampled for this trace: one rubric judge, `gemini-rubric`, returned the label `ensemble_supported` with its reasoning as persisted. That label comes from the shared contract. One judge produced it.*

### Red Team

![Red Team page listing scenarios by defense, with PII-001 selected and its recorded executions, including one that differed from expectation before the scenario was revised](docs/assets/screenshots/red-team.png)

*Each scenario states what should happen, and each stored execution records what did, as separate fields. PII-001 is selected. Version 1 was stopped by Llama Guard before redaction could be observed, so that execution is kept as "differs from expectation" and version 2 isolates redaction. Across the 43 recorded executions, 41 were caught and 2 were missed. Both misses are GAP-001, a scenario kept on purpose: the schema rail checks citation ids, and no deterministic layer checks whether the quoted text appears in the cited chunk. A recorded result shows whether a defense acts on one controlled input. It does not show how often real attackers get through.*

### The investigator

![Agent page with a list of stored investigations and a featured case that reaches a best-supported hypothesis marked high confidence, not proven](docs/assets/screenshots/agent.png)

*The featured case on the right is a judge disagreement cluster. The investigator ranks hypotheses from stored records, reports "high confidence, not proven", and states why it stopped: a leading hypothesis met every prediction it made and no rival was also supported. It did this in 7 queries with no model call. The case is labeled Fixture replay. A fixture replay runs a known case world through the real investigator with a scripted planner and no model. It shows how the investigator reasons and bounds its claims. It says nothing about the live platform, and the kappa of 0.31 in its text belongs to the fixture, not to the recorded reading of 0.516. The list keeps an errored run and two abstentions because an abstention is a valid result. Of the 7 stored investigations, 6 are fixture replays and 1 is a live run, which abstained.*

## What makes it different

**Layered guardrails at distinct points.** Input, retrieval and output controls sit at different places in one request and fail differently on purpose. Input rails fail closed because hostile input should never reach retrieval. The faithfulness check fails open because a Gemini outage should cost evaluation coverage and not availability.

**Two-tier judging.** A cheap judge scores everything. A second, rubric-based judge reviews a deterministic sample. The sample is a hash of the trace id, so a retry or a replay at the same rate picks the same traces.

**An evaluator that is itself measured.** The judge is scored against labeled data, with explicit thresholds and a documented state machine. The reading is stored, dated and shown, including when it says the judge is degraded. The failover step, a gated judge that bypasses a drifted judge, is built and tested but not yet wired into the running consumers.

**Evidence that outlives the stream.** Topics expire. The platform copies what matters into durable tables and a verified archive, and the public demo is built from that archive.

**Typed access to the evidence.** The MCP server gives typed access to the same records the screens show, through nine tools that issue only SELECTs. The investigator refuses to start unless its tool surface is exactly those nine.

**An investigator that reasons from evidence.** A model proposes competing hypotheses and the predictions that would tell them apart. Code runs the queries, evaluates each prediction against what came back, and decides. A claim can cite only a record that one of this investigation's own queries returned, so every conclusion rests on evidence the investigator retrieved. The result is a cause with its confidence, or a plain statement that the evidence is not there. Investigation and control are separate concerns by design: the investigator recommends one verification for a person to run, and failover lives in its own tested controller.

## Engineering decisions

**Deterministic evidence before LLM interpretation.** The planner is asked for hypotheses and predictions as structured fields. Nine deterministic evaluators read each prediction against the results of the query it names. The model never decides what is true. The cost is a narrower investigator than a free-form agent, and more abstentions.

**Calibrate the evaluator, do not trust it.** A judge is a model, and a model can be wrong in ways its own scores hide. The platform measures agreement with labeled data and exposes the number. The cost is a need for labeled data, and weak resolution: the rubric judge's scores take only three values, so thresholds have little room to move.

**Investigation and control kept apart.** The investigator reads evidence and recommends. Failover logic lives in a separate, tested controller. The cost is that a person acts on the recommendation. One caveat on the read-only MCP tools: it rests on the tools issuing only SELECTs, a read-only annotation on each tool, and tests, not on a database-level guard.

**A missing record is not an unavailable source, and neither is a confirmed negative.** An investigation opens with a read of the one source it cannot do without. If that source fails twice, it abstains with a "critical evidence unavailable" reason. A query that ran and returned nothing is recorded as an empty result. The report keeps all three cases apart. The cost is that some investigations end in an abstention where a guess was available.

**Bounded spend.** Every place that calls a model has a cap in code. The faithfulness check stops at $0.02 per call, $5 per run and $25 per day. The investigator's planner has a $0.25 cap of its own and shares a $0.10 cap across the process. A Red Team run lets at most one request continue past the input rails to the model. Every cost recorded in the repository is an estimate from usage metadata, not a billing figure. The cost is that a cap skips evaluation, which the faithfulness check records as "skipped" and does not turn into a failed request.

## Results

Each result is one measurement with its main limit. The numbers come from committed files in `docs/measurements/`.

**1. The rubric judge ranks hallucinations above faithful answers.** On held-out labeled FinQA hallucination data it reached ROC-AUC 0.83 (95% interval 0.74 to 0.92) and average precision 0.55 (0.38 to 0.73). At the selected threshold it caught 16 of the 22 hallucinations (recall 0.73) and flagged 9 of 128 faithful answers (precision 0.64). The limit is resolution: the judge's scores take only three values, and with 22 hallucinations in the held-out rows the intervals are wide. The measurement was zero-shot, without the FinanceBench peer examples the live judge adds.
Source: `calibration/calibration_summary.json`, `cost-accuracy/day10d-replay.json`.

**2. The platform reports how far its judge can be trusted.** Scored against unseen labeled rows, the rubric judge's agreement with the labels is kappa 0.516. That sits between the entry threshold (0.43) and the recovery threshold (0.54), so the state is degraded and not drifted. The healthy baseline is 0.605. The limit is that this is one reading on a small sample, so it shows no trend, and nothing runs it on a schedule yet.
Source: `reliability/canary-live-smoke-d6p2.json`.

**3. The gateway holds its targets at 0.5 and 1 request per second and crashes at 2.** At those two rates it met its targets of p95 under 3 s, p99 under 5 s and under 1% errors, with p95 between 2.7 and 2.9 s. At 2 per second only 53 of 120 requests were answered and the gateway process crashed, and a second run crashed at 1 per second. Llama Guard is the likely trigger, because one GPU-resident model is called from several threads without a lock, but this was not isolated. The retrieval rail dominated latency, because Prompt Guard 2 checks the retrieved chunks one at a time. No answered request was lost silently: all 168 in the first run and all 55 in the second have an event, a verdict and a persisted row, and the unanswered ones left no event. The limit is scope. The test covers the guardrail and event path with generation and the judges excluded, and no rate passed twice, so it establishes no capacity figure. The observed limit is a crash.
Source: `load/`.

**4. The investigator reaches safe conclusions on known-answer incidents.** Nine incidents with known outcomes were frozen before the investigator ran on them: seven call for a diagnosis and two call for an abstention. Scoring is deterministic, so nothing is graded by a model. In a live pass with a Gemini planner it passed 6 of 9, and all 9 were safe, meaning none reached a wrong conclusion. The diagnostic outcome was 4 pass, 3 incomplete and 0 fail. A scripted planner passed 5 of 9, and an always-abstain baseline passed 1 of 9. The limit is size: it is one run on nine cases, one of the three incomplete results is a service timeout and not an agent failure, and one of the four passes is weaker than the scorer credits because the cited evidence lacks a record the case requires.
Source: `investigator/heldout/`.

## Reliability, security and known limits

- **Failure behavior.** Input rails, schema and phrase rails fail closed. The faithfulness check fails open. Event delivery is at most once. Event publishing and Gemini calls are switched on by configuration, and the committed defaults leave both off.
- **Starting work.** Red Team runs and investigations start only through a password-gated route. The gate fails closed when no password is set and locks out after five failed attempts. Reads are open.
- **Not wired.** The drift controller and the drift-gated judge are tested but not connected to the running consumers, and the canary runs by hand.
- **One model for both tiers.** The flash and rubric judges default to the same Gemini model, so the second tier is a different prompt and sample, not an independent stronger judge. The flash tier has no scores on labeled data.
- **One judge in the frontier tier.** HHEM-2.1 is implemented and disabled. Patronus Lynx and Prometheus were measured and judged not viable, so no adapter exists.
- **A lost record.** One real disagreement between the two tiers was observed on Oct 3, flash 1.0 against frontier 0.0 on an Amazon question. Its stream records expired before they were archived. Only a capture marked historical remains, so the archive holds no live disagreement.
- **CI.** The workflow runs deterministic checks only: lint, types and the tests that do not need a model or a running stack. A green run does not measure scale or hallucination rates.

## Repository

```
fin-sentry/
├── finsentry/        Python package
│   ├── gateway/        FastAPI gateway, NeMo adapter, circuit breaker, metrics relay
│   ├── rails/          input, retrieval and output rails
│   ├── judges/         flash judge and its three metrics
│   ├── frontier/       rubric judge, sampler, verdict reduction, peer retrieval
│   ├── consumer/       flash and frontier consumers
│   ├── events/         event schema, topics, producer
│   ├── dashboard/      service that serves the RisingWave views and the canary reading
│   ├── reliability/    kappa, drift controller, gated judge, canary
│   ├── mcp/            MCP server and the nine read tools
│   ├── investigator/   bounded investigator, evaluators, evaluation cases
│   ├── redteam/        scenario registry and executors
│   ├── archive/        export, verify and restore of the evidence archive
│   └── ...             calibration, db, ingestion, observability, risingwave
├── web/              Next.js 16 app
├── infra/            RisingWave sources and views, nginx config
├── config/           rail failure settings
├── docs/             build log, ADRs, measurements, demo archive, deploy notes
├── tests/            pytest suite
├── scripts/          measurement, calibration and load-test scripts
└── docker-compose.dev.yml   Postgres, Redpanda, RisingWave, the dashboard service and three gateway replicas behind nginx
```

The build log (`docs/build-log.md`) records each working session with its checks. `docs/measurements/` holds the raw outputs behind the Results section, and `docs/adr/` holds the architecture decision records.

## Technology

- **Gateway and guardrails:** Python 3.13, FastAPI, NeMo Guardrails, Llama Prompt Guard 2, Llama Guard 3 (1B), Presidio, spaCy, tenacity
- **Models:** Ollama with llama3.1:8b, Gemini 3.6 Flash on Vertex AI, bge-small-en-v1.5 embeddings
- **Streaming and storage:** Redpanda, RisingWave, PostgreSQL with pgvector, aiokafka, psycopg
- **Data:** SEC EDGAR filings through edgartools, FinQA hallucination set, FinanceBench
- **Interfaces and telemetry:** Model Context Protocol Python SDK, OpenTelemetry, Server-Sent Events
- **Frontend:** Next.js 16, React 19, TypeScript, Tailwind CSS
- **Quality and delivery:** pytest, Vitest, Playwright, ruff, mypy, ESLint, GitHub Actions, Docker Compose, Vercel
