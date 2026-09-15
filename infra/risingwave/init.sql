-- RisingWave streaming SQL init script.
-- Run via scripts/init_risingwave.py (or psql directly against RisingWave port 4566).
--
-- Sources: two Redpanda topics consumed as append-only sources.
-- Materialized views: six aggregations for the dashboard.
-- Aggregations use GROUP BY date_trunc(...) time buckets rather than event-time TUMBLE,
-- so each event is visible immediately on sparse evaluation traffic
-- (event-time watermarks do not advance without continuous input).
--
-- Topic layout:
--   rag-responses    -> RagResponseEvent   (schema_version 1.0)   -> source: rag_events
--   judge-verdicts   -> JudgeVerdictEvent  (schema_version 1.0)   -> source: judge_verdicts
--
-- RisingWave uses PostgreSQL wire protocol - syntax below is RisingWave SQL.

-- ---------------------------------------------------------------------------
-- Sources
-- ---------------------------------------------------------------------------

CREATE SOURCE IF NOT EXISTS rag_events (
    schema_version        VARCHAR,
    event_id              VARCHAR,
    app_trace_id          VARCHAR,
    timestamp_utc         TIMESTAMPTZ,
    status                VARCHAR,
    endpoint              VARCHAR,
    query                 VARCHAR,
    ticker                VARCHAR,
    retrieved_chunk_ids   JSONB,
    retrieved_chunks_text JSONB,
    answer                VARCHAR,
    citations             JSONB,
    confidence            VARCHAR,
    model_used            VARCHAR,
    input_rail_status     VARCHAR,
    output_rail_trace_snapshot JSONB,
    block_reason          VARCHAR,
    block_rail            VARCHAR,
    error_kind            VARCHAR,
    error_detail          VARCHAR,
    total_latency_ms      INT
)
WITH (
    connector        = 'kafka',
    topic            = 'rag-responses',
    properties.bootstrap.server = 'redpanda:9092',
    scan.startup.mode = 'earliest'
)
FORMAT PLAIN ENCODE JSON;


CREATE SOURCE IF NOT EXISTS judge_verdicts (
    schema_version              VARCHAR,
    event_id                    VARCHAR,
    source_event_id             VARCHAR,
    app_trace_id                VARCHAR,
    timestamp_utc               TIMESTAMPTZ,
    faithfulness_score          DOUBLE PRECISION,
    faithfulness_status         VARCHAR,
    answer_relevance_score      DOUBLE PRECISION,
    answer_relevance_status     VARCHAR,
    context_relevance_score     DOUBLE PRECISION,
    context_relevance_status    VARCHAR,
    total_input_tokens          INT,
    total_output_tokens         INT,
    total_thoughts_tokens       INT,
    total_gemini_calls          INT,
    judge_tier                  VARCHAR,
    judge_model                 VARCHAR,
    status                      VARCHAR,
    evaluation_latency_ms       INT,
    total_cost_usd              DOUBLE PRECISION
)
WITH (
    connector        = 'kafka',
    topic            = 'judge-verdicts',
    properties.bootstrap.server = 'redpanda:9092',
    scan.startup.mode = 'earliest'
)
FORMAT PLAIN ENCODE JSON;


-- ---------------------------------------------------------------------------
-- Materialized views — teardown (reverse dependency order, re-run safe)
-- ---------------------------------------------------------------------------

DROP MATERIALIZED VIEW IF EXISTS mv_ticker_quality_1h;
DROP MATERIALIZED VIEW IF EXISTS mv_judge_cost_1m;
DROP MATERIALIZED VIEW IF EXISTS mv_judge_usage_1m;
DROP MATERIALIZED VIEW IF EXISTS mv_relevance_1m;
DROP MATERIALIZED VIEW IF EXISTS mv_faithfulness_1m;
DROP MATERIALIZED VIEW IF EXISTS mv_request_throughput_1m;


-- ---------------------------------------------------------------------------
-- Materialized views — recreate with date_trunc time buckets
-- ---------------------------------------------------------------------------

-- 1. Request throughput: query count and status breakdown per 1-minute bucket.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_request_throughput_1m AS
SELECT
    date_trunc('minute', timestamp_utc)                        AS window_start,
    date_trunc('minute', timestamp_utc) + INTERVAL '1 minute'  AS window_end,
    COUNT(*)                                                   AS total_requests,
    COUNT(*) FILTER (WHERE status = 'success')                 AS success_count,
    COUNT(*) FILTER (WHERE status = 'blocked')                 AS blocked_count,
    COUNT(*) FILTER (WHERE status = 'error')                   AS error_count,
    AVG(total_latency_ms)                                      AS avg_latency_ms,
    APPROX_PERCENTILE(0.95) WITHIN GROUP (ORDER BY total_latency_ms) AS p95_latency_ms
FROM rag_events
GROUP BY date_trunc('minute', timestamp_utc);


-- 2. Faithfulness score distribution per 1-minute bucket.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_faithfulness_1m AS
SELECT
    date_trunc('minute', timestamp_utc)                        AS window_start,
    date_trunc('minute', timestamp_utc) + INTERVAL '1 minute'  AS window_end,
    COUNT(*)                                                     AS verdicts_count,
    AVG(faithfulness_score)                                      AS avg_faithfulness,
    COUNT(*) FILTER (WHERE faithfulness_status = 'complete')     AS complete_count,
    COUNT(*) FILTER (WHERE faithfulness_status LIKE 'skipped_%') AS skipped_count
FROM judge_verdicts
WHERE faithfulness_score IS NOT NULL
GROUP BY date_trunc('minute', timestamp_utc);


-- 3. Answer + Context relevance per 1-minute bucket.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_relevance_1m AS
SELECT
    date_trunc('minute', timestamp_utc)                        AS window_start,
    date_trunc('minute', timestamp_utc) + INTERVAL '1 minute'  AS window_end,
    COUNT(*)                        AS verdicts_count,
    AVG(answer_relevance_score)     AS avg_answer_relevance,
    AVG(context_relevance_score)    AS avg_context_relevance
FROM judge_verdicts
WHERE answer_relevance_score IS NOT NULL
   OR context_relevance_score IS NOT NULL
GROUP BY date_trunc('minute', timestamp_utc);


-- 4. Gemini token usage and cost per 1-minute bucket.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_judge_usage_1m AS
SELECT
    date_trunc('minute', timestamp_utc)                        AS window_start,
    date_trunc('minute', timestamp_utc) + INTERVAL '1 minute'  AS window_end,
    SUM(total_input_tokens)    AS input_tokens_total,
    SUM(total_output_tokens)   AS output_tokens_total,
    SUM(total_thoughts_tokens) AS thoughts_tokens_total,
    SUM(total_gemini_calls)    AS gemini_calls_total,
    SUM(total_cost_usd)        AS cost_total_usd
FROM judge_verdicts
GROUP BY date_trunc('minute', timestamp_utc);


-- 5. Judge cost per 1-minute bucket.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_judge_cost_1m AS
SELECT
    date_trunc('minute', timestamp_utc)                        AS window_start,
    date_trunc('minute', timestamp_utc) + INTERVAL '1 minute'  AS window_end,
    SUM(total_cost_usd) AS cost_total_usd
FROM judge_verdicts
GROUP BY date_trunc('minute', timestamp_utc);


-- 6. Per-ticker quality summary: faithfulness + relevance per 1-hour bucket.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_ticker_quality_1h AS
SELECT
    date_trunc('hour', r.timestamp_utc)                        AS window_start,
    date_trunc('hour', r.timestamp_utc) + INTERVAL '1 hour'    AS window_end,
    r.ticker,
    COUNT(*)                        AS request_count,
    AVG(v.faithfulness_score)       AS avg_faithfulness,
    AVG(v.answer_relevance_score)   AS avg_answer_relevance,
    AVG(v.context_relevance_score)  AS avg_context_relevance
FROM rag_events AS r
JOIN judge_verdicts AS v ON v.app_trace_id = r.app_trace_id
WHERE r.status = 'success'
GROUP BY date_trunc('hour', r.timestamp_utc), r.ticker;
