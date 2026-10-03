ALTER TABLE golden_set ADD COLUMN IF NOT EXISTS embedding vector(384);

CREATE INDEX IF NOT EXISTS golden_set_embedding_hnsw_idx
    ON golden_set USING hnsw (embedding vector_cosine_ops);
