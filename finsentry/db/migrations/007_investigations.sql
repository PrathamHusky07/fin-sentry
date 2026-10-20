-- Durable incident investigations. One row is one investigation session, kept so a page
-- refresh or a server restart reopens the recorded session and never starts a new one.
--
-- "status" is the lifecycle. running is the only state that changes. completed means a report
-- was produced and stored, and an abstention is a completed outcome, never an error. failed
-- means the investigator raised. interrupted means the process running it stopped before it
-- finished (a shutdown, or a heartbeat that went stale). Neither is resumable: there is no
-- resume, so a new investigation is started instead.
--
-- "origin" says where the evidence came from. live is the running platform read through the
-- nine MCP tools. fixture is a known-answer case world replayed through the same code, kept
-- apart so a fixture is never read as an outcome on the live platform.
--
-- "state" is the final InvestigationState (ledger, executed queries, usage, gaps) and "report"
-- the IncidentReport. Both are stored as the contracts serialize them. "usage" adds what the
-- model calls cost. Nothing here is a model's free-text reasoning.

CREATE TABLE IF NOT EXISTS investigations (
    investigation_id UUID        PRIMARY KEY,
    incident_id      TEXT        NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at      TIMESTAMPTZ,
    heartbeat_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    status           TEXT        NOT NULL
        CHECK (status IN ('running', 'completed', 'failed', 'interrupted')),
    origin           TEXT        NOT NULL CHECK (origin IN ('live', 'fixture')),
    planner          TEXT        NOT NULL,
    agent_version    TEXT        NOT NULL,
    request          JSONB       NOT NULL,
    request_key      TEXT        NOT NULL,
    outcome          TEXT        CHECK (outcome IN ('diagnosis', 'abstention')),
    stopping_reason  TEXT,
    state            JSONB,
    report           JSONB,
    usage            JSONB,
    error            TEXT,
    -- A completed investigation always carries its outcome and report, and no other does.
    CHECK ((status = 'completed') = (outcome IS NOT NULL AND report IS NOT NULL)),
    -- A running investigation is unfinished, and every other state has an end time.
    CHECK ((status = 'running') = (finished_at IS NULL)),
    -- A failed or interrupted investigation says why, and no other does.
    CHECK ((status IN ('failed', 'interrupted')) = (error IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS investigations_created_idx
    ON investigations (created_at DESC);

-- At most one investigation runs at a time. Each one starts a tool server and may call the
-- model, and the gateway runs as several replicas, so the database is the arbiter and not a
-- process lock. Finished rows are not constrained, so every session is kept.
CREATE UNIQUE INDEX IF NOT EXISTS investigations_one_running
    ON investigations ((true)) WHERE status = 'running';

CREATE TABLE IF NOT EXISTS investigation_events (
    investigation_id UUID             NOT NULL REFERENCES investigations (investigation_id),
    seq              INTEGER          NOT NULL,
    at               TIMESTAMPTZ      NOT NULL,
    elapsed_s        DOUBLE PRECISION NOT NULL,
    kind             TEXT             NOT NULL,
    payload          JSONB            NOT NULL,
    PRIMARY KEY (investigation_id, seq)
);
