-- DESTRUCTIVE. Drops every materialized view so init.sql can recreate it from the topics.
-- Run only through `python scripts/init_risingwave.py --destroy-history-and-rebuild`.
--
-- The topics expire old events, so a rebuilt view holds only what the topics still hold today.
-- Every view loses the history the topics no longer have. Measured on the live store before this
-- split: mv_request_throughput_1m held 578 requests against 333 events left in the topic, and
-- mv_judge_cost_1m held $4.65 against $3.60 in the source rows. Use this only on a database whose
-- history does not matter, or after the stored rows have been exported.
--
-- Reverse dependency order.

DROP MATERIALIZED VIEW IF EXISTS mv_request_latency_exact_1m;
DROP MATERIALIZED VIEW IF EXISTS mv_frontier_disagreement_1m;
DROP MATERIALIZED VIEW IF EXISTS mv_frontier_verdict_rate_1m;
DROP MATERIALIZED VIEW IF EXISTS mv_ticker_quality_1h;
DROP MATERIALIZED VIEW IF EXISTS mv_judge_cost_1m;
DROP MATERIALIZED VIEW IF EXISTS mv_judge_usage_1m;
DROP MATERIALIZED VIEW IF EXISTS mv_relevance_1m;
DROP MATERIALIZED VIEW IF EXISTS mv_faithfulness_1m;
DROP MATERIALIZED VIEW IF EXISTS mv_request_throughput_1m;
