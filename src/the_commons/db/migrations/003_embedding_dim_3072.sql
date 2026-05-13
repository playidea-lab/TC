-- Gemini Embedding 2 native = 3072-dim, but pgvector HNSW는 2000-dim 제한.
-- v0.1은 HNSW 유지를 위해 Matryoshka 축소 1024 사용 (API의 output_dimensionality).
-- 002에서 이미 vector(1024)이므로 type 변경 불필요 — 단순 안전망.

DROP INDEX IF EXISTS idx_evidence_embedding_hnsw;
ALTER TABLE evidence ALTER COLUMN embedding TYPE vector(1024);
CREATE INDEX idx_evidence_embedding_hnsw
    ON evidence
    USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL AND deprecated = FALSE;
