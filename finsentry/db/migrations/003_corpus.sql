CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS corpus (
    id               TEXT        PRIMARY KEY,
    ticker           TEXT        NOT NULL,
    filing_type      TEXT        NOT NULL,
    accession_number TEXT        NOT NULL,
    filing_date      DATE        NOT NULL,
    period_of_report DATE,
    chunk_index      INTEGER     NOT NULL,
    chunk_text       TEXT        NOT NULL,
    chunk_tokens     INTEGER     NOT NULL,
    embedding        vector(384) NOT NULL,
    source_url       TEXT        NOT NULL,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS corpus_ticker_filing_type_idx
    ON corpus (ticker, filing_type);

CREATE INDEX IF NOT EXISTS corpus_embedding_hnsw_idx
    ON corpus USING hnsw (embedding vector_cosine_ops);
