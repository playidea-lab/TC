-- 인덱스 — 조회 패턴에 맞춰 핵심만

-- Evidence 검색 (deprecated=FALSE인 active record 위주)
CREATE INDEX idx_evidence_tier_active
    ON evidence (tier)
    WHERE deprecated = FALSE;

CREATE INDEX idx_evidence_modality_band_active
    ON evidence (modality, sample_count_band)
    WHERE deprecated = FALSE;

CREATE INDEX idx_evidence_created_at
    ON evidence (created_at DESC);

-- 매치메이커 vector retrieve용 HNSW (Gemini 1024-dim, cosine)
-- HNSW가 IVFFlat보다 정확도·속도 균형 우수. v0.1 corpus 규모(1만~10만)엔 적합.
CREATE INDEX idx_evidence_embedding_hnsw
    ON evidence
    USING hnsw (embedding vector_cosine_ops)
    WHERE embedding IS NOT NULL AND deprecated = FALSE;

-- Cluster
CREATE INDEX idx_cluster_real_count_desc
    ON cluster (real_count DESC);

CREATE INDEX idx_cluster_problem_bucket
    ON cluster (problem_fingerprint_bucket);

-- Reciprocity event (success metric verdict 보고서용)
CREATE INDEX idx_reciprocity_type_created
    ON reciprocity_event (event_type, created_at DESC);

CREATE INDEX idx_reciprocity_origin
    ON reciprocity_event (origin);

-- Retirement audit
CREATE INDEX idx_retirement_synthetic
    ON retirement_audit (synthetic_evidence_id);

CREATE INDEX idx_retirement_cluster
    ON retirement_audit (cluster_id);
