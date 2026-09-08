CREATE TABLE IF NOT EXISTS hallucination_bench (
    id               TEXT        PRIMARY KEY,
    question         TEXT        NOT NULL,
    context          TEXT        NOT NULL,
    response         TEXT        NOT NULL,
    is_hallucination BOOLEAN     NOT NULL,
    source           TEXT        NOT NULL DEFAULT 'finqa-halluc',
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
