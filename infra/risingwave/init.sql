-- RisingWave streaming SQL init script.
-- Run via scripts/init_risingwave.py (or psql directly against RisingWave port 4566).
--
-- Sources: two Redpanda topics consumed as append-only sources.
-- Materialized views: five windowed aggregations for the dashboard.
--
-- Topic layout:
--   rag-responses    -> RagResponseEvent   (schema_version 1.0)   -> source: rag_events
--   judge-verdicts   -> JudgeVerdictEvent  (schema_version 1.0)   -> source: judge_verdicts
--
-- RisingWave uses PostgreSQL wire protocol; syntax below is RisingWave SQL.

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
-- Materialized views
-- ---------------------------------------------------------------------------

-- 1. Request throughput: query count and status breakdown per 1-minute window.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_request_throughput_1m AS
SELECT
    window_start,
    window_end,
    COUNT(*)                                                   AS total_requests,
    COUNT(*) FILTER (WHERE status = 'success')                 AS success_count,
    COUNT(*) FILTER (WHERE status = 'blocked')                 AS blocked_count,
    COUNT(*) FILTER (WHERE status = 'error')                   AS error_count,
    AVG(total_latency_ms)                                      AS avg_latency_ms,
    PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_latency_ms) AS p95_latency_ms
FROM TUMBLE(rag_events, timestamp_utc, INTERVAL '1 minute')
GROUP BY window_start, window_end;


-- 2. Faithfulness score distribution per 5-minute window (success events only).
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_faithfulness_5m AS
SELECT
    window_start,
    window_end,
    COUNT(*)                                                        AS verdicts_count,
    AVG(faithfulness_score)                                         AS avg_faithfulness,
    COUNT(*) FILTER (WHERE faithfulness_status = 'complete')        AS complete_count,
    COUNT(*) FILTER (WHERE faithfulness_status LIKE 'skipped_%')    AS skipped_count
FROM TUMBLE(judge_verdicts, timestamp_utc, INTERVAL '5 minutes')
WHERE faithfulness_score IS NOT NULL
GROUP BY window_start, window_end;


-- 3. Answer + Context relevance per 5-minute window.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_relevance_5m AS
SELECT
    window_start,
    window_end,
    COUNT(*)                                AS verdicts_count,
    AVG(answer_relevance_score)             AS avg_answer_relevance,
    AVG(context_relevance_score)            AS avg_context_relevance
FROM TUMBLE(judge_verdicts, timestamp_utc, INTERVAL '5 minutes')
WHERE answer_relevance_score IS NOT NULL
   OR context_relevance_score IS NOT NULL
GROUP BY window_start, window_end;


-- 4. Gemini token usage and cost per 5-minute window.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_judge_usage_5m AS
SELECT
    window_start,
    window_end,
    SUM(total_input_tokens)    AS input_tokens_total,
    SUM(total_output_tokens)   AS output_tokens_total,
    SUM(total_thoughts_tokens) AS thoughts_tokens_total,
    SUM(total_gemini_calls)    AS gemini_calls_total,
    SUM(total_cost_usd)        AS cost_total_usd
FROM TUMBLE(judge_verdicts, timestamp_utc, INTERVAL '5 minutes')
GROUP BY window_start, window_end;


-- 6. Judge cost aggregated per 5-minute window (dedicated cost view).
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_judge_cost_5m AS
SELECT
    window_start,
    window_end,
    SUM(total_cost_usd) AS cost_total_usd
FROM TUMBLE(judge_verdicts, timestamp_utc, INTERVAL '5 minutes')
GROUP BY window_start, window_end;


-- 5. Per-ticker quality summary: faithfulness + relevance rolling 1-hour window.
CREATE MATERIALIZED VIEW IF NOT EXISTS mv_ticker_quality_1h AS
SELECT
    window_start,
    window_end,
    r.ticker,
    COUNT(*)                        AS request_count,
    AVG(v.faithfulness_score)       AS avg_faithfulness,
    AVG(v.answer_relevance_score)   AS avg_answer_relevance,
    AVG(v.context_relevance_score)  AS avg_context_relevance
FROM TUMBLE(rag_events, timestamp_utc, INTERVAL '1 hour') AS r
JOIN judge_verdicts v ON v.app_trace_id = r.app_trace_id
WHERE r.status = 'success'
GROUP BY window_start, window_end, r.ticker;
