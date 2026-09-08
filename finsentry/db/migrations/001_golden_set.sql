CREATE TABLE IF NOT EXISTS golden_set (
    id              TEXT        PRIMARY KEY,
    question        TEXT        NOT NULL,
    expected_answer TEXT        NOT NULL,
    doc_id          TEXT        NOT NULL,
    source          TEXT        NOT NULL DEFAULT 'financebench',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
