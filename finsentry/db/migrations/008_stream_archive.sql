-- The streaming records the demo depends on, kept in Postgres so they do not depend on the
-- Redpanda topics. rag-responses, judge-verdicts and rag-frontier-verdicts are the only copy of
-- a trace and its verdicts, and RisingWave reads them from the topics. A record is identified
-- by the sha256 of its canonical JSON value, so loading the same archive twice adds nothing.
-- The Red Team and Agent tables are already durable Postgres tables and are not copied here.
CREATE TABLE IF NOT EXISTS stream_archive (
    topic            TEXT        NOT NULL,
    record_sha256    TEXT        NOT NULL,
    source_offset    BIGINT      NOT NULL,
    record_key       TEXT,
    record_timestamp TIMESTAMPTZ NOT NULL,
    value            JSONB       NOT NULL,
    archived_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (topic, record_sha256)
);

CREATE INDEX IF NOT EXISTS stream_archive_topic_time_idx
    ON stream_archive (topic, record_timestamp);
