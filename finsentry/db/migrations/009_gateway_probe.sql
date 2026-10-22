-- Gateway round-trip probe runs. One row is one run of finsentry.observability.gateway_probe: a
-- burst of timed GET requests to the gateway health route, which runs no retrieval and no model.
-- It is telemetry about reaching the gateway, kept apart from the product evidence (the stream
-- topics, stream_archive, the Red Team tables and the Agent tables), and nothing here is a RAG
-- request latency. "latencies_ms" holds every timed request so the summary can be recomputed.
CREATE TABLE IF NOT EXISTS gateway_probe_runs (
    id           BIGSERIAL        PRIMARY KEY,
    measured_at  TIMESTAMPTZ      NOT NULL DEFAULT now(),
    target       TEXT             NOT NULL,
    samples      INTEGER          NOT NULL CHECK (samples > 0),
    latencies_ms DOUBLE PRECISION[] NOT NULL,
    median_ms    DOUBLE PRECISION NOT NULL,
    p95_ms       DOUBLE PRECISION NOT NULL,
    max_ms       DOUBLE PRECISION NOT NULL
);

CREATE INDEX IF NOT EXISTS gateway_probe_runs_measured_at_idx
    ON gateway_probe_runs (measured_at DESC);
