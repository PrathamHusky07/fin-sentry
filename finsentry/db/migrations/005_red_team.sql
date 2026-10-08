-- Red Team Console persistence. One run is one operator request. One execution
-- is one scenario fired once inside a run, so a rerun is always a new row and is
-- never collapsed by scenario id.
--
-- "state" is the execution lifecycle. "outcome" is the five-state security
-- result and stays NULL until the execution finishes. "expected" is a copy of the
-- scenario's expectation taken when the execution started, kept apart from the
-- observed outcome so a configured expectation is never mistaken for a result.

CREATE TABLE IF NOT EXISTS red_team_runs (
    run_id               UUID        PRIMARY KEY,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
    finished_at          TIMESTAMPTZ,
    status               TEXT        NOT NULL
        CHECK (status IN ('running', 'completed', 'failed')),
    scenario_ids         TEXT[]      NOT NULL,
    allow_judge_assisted BOOLEAN     NOT NULL DEFAULT FALSE,
    failure_reason       TEXT
);

CREATE INDEX IF NOT EXISTS red_team_runs_created_idx
    ON red_team_runs (created_at DESC);

CREATE TABLE IF NOT EXISTS red_team_executions (
    execution_id     UUID        PRIMARY KEY,
    run_id           UUID        NOT NULL REFERENCES red_team_runs (run_id),
    seq              INTEGER     NOT NULL,
    scenario_id      TEXT        NOT NULL,
    scenario_version INTEGER     NOT NULL,
    category         TEXT        NOT NULL,
    target_layer     TEXT        NOT NULL,
    mode             TEXT        NOT NULL
        CHECK (mode IN ('deterministic', 'judge_assisted')),
    expected         JSONB       NOT NULL,
    state            TEXT        NOT NULL
        CHECK (state IN ('queued', 'running', 'finished')),
    outcome          TEXT
        CHECK (outcome IN (
            'caught', 'missed', 'evaluator_unavailable', 'execution_failed', 'inconclusive'
        )),
    acting_layer     TEXT,
    acting_check     TEXT,
    expectation      TEXT
        CHECK (expectation IN ('met', 'not_met', 'not_assessable')),
    reason           TEXT,
    evidence         JSONB       NOT NULL DEFAULT '{}'::jsonb,
    trace_ref        TEXT,
    gemini_calls     INTEGER     NOT NULL DEFAULT 0,
    cost_usd         NUMERIC(12, 6) NOT NULL DEFAULT 0,
    started_at       TIMESTAMPTZ,
    finished_at      TIMESTAMPTZ,
    duration_ms      INTEGER,
    -- A finished execution always carries an outcome, and an unfinished one never does.
    CHECK ((state = 'finished') = (outcome IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS red_team_executions_run_idx
    ON red_team_executions (run_id, seq);
CREATE INDEX IF NOT EXISTS red_team_executions_scenario_idx
    ON red_team_executions (scenario_id, started_at DESC);
