-- TC v0.1 초기 schema
-- pgvector extension 활성화 + 핵심 테이블 6개

CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- Enums
-- ============================================================================

CREATE TYPE evidence_tier AS ENUM ('real', 'synthetic');
CREATE TYPE evidence_origin AS ENUM ('internal', 'external');
CREATE TYPE reciprocity_event_type AS ENUM ('loop_closure', 'promote', 'contradicts');

-- ============================================================================
-- Evidence (L1 immutable)
-- pcq 2.x run_record 전체를 JSONB로 보존 + 자주 쓰는 필드 컬럼화
-- ============================================================================

CREATE TABLE evidence (
    evidence_id            TEXT PRIMARY KEY,            -- 예: ev-a1b2c3
    tier                   evidence_tier NOT NULL,
    outreach_origin        evidence_origin NOT NULL,

    -- pcq 2.x run_record 원본 (SSOT, immutable)
    run_record             JSONB NOT NULL,

    -- 검색용 추출 필드 (run_record로부터 derive)
    modality               TEXT NOT NULL,                -- tabular/vision/nlp/...
    sample_count_band      TEXT NOT NULL,                -- '1k-10k', '10k-100k'
    intent_goal            TEXT NOT NULL,
    primary_metric_name    TEXT,
    primary_metric_value   DOUBLE PRECISION,

    -- Attribution
    contributor_id         TEXT,                          -- nullable (anonymous OK v0.1)
    content_hash           TEXT NOT NULL UNIQUE,         -- SHA256, immutability 검증
    created_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Synthetic 전용 (tier='synthetic' 시 필수)
    synthetic_source       JSONB,                          -- {source_model, prompt_hash, generated_at, verifier}

    -- L3 visibility (mutable)
    deprecated             BOOLEAN NOT NULL DEFAULT FALSE,
    deprecated_reason      TEXT,
    deprecated_at          TIMESTAMPTZ,

    -- Embedding (Gemini Embedding 2 — 1024-dim 가정, 모델 실측 후 조정)
    embedding              vector(1024),                  -- nullable until embed pipeline 처리
    embedding_template_ver TEXT NOT NULL DEFAULT 'v1',

    -- synthetic은 attribution 강제
    CONSTRAINT synthetic_attribution_required
        CHECK (tier = 'real' OR synthetic_source IS NOT NULL)
);

COMMENT ON TABLE evidence IS
    'L1 immutable evidence store. pcq 2.x run_record를 JSONB로 보존, '
    '자주 쓰는 필드는 컬럼화. L3 deprecated 플래그는 mutable.';

-- ============================================================================
-- Cluster (problem 영역 × recipe — retirement 판정 단위)
-- ============================================================================

CREATE TABLE cluster (
    cluster_id                  TEXT PRIMARY KEY,
    problem_fingerprint_bucket  TEXT NOT NULL,            -- 예: 'tabular-binary-10k-100k'
    recipe_id                   TEXT NOT NULL,
    real_count                  INTEGER NOT NULL DEFAULT 0,
    synthetic_count             INTEGER NOT NULL DEFAULT 0,
    last_real_at                TIMESTAMPTZ,
    UNIQUE (problem_fingerprint_bucket, recipe_id)
);

-- Evidence ↔ Cluster (many-to-many)
CREATE TABLE evidence_cluster (
    evidence_id  TEXT NOT NULL REFERENCES evidence(evidence_id),
    cluster_id   TEXT NOT NULL REFERENCES cluster(cluster_id),
    PRIMARY KEY (evidence_id, cluster_id)
);

-- ============================================================================
-- Retirement audit (synthetic 자동 deprecation 추적)
-- ============================================================================

CREATE TABLE retirement_audit (
    retirement_id           BIGSERIAL PRIMARY KEY,
    synthetic_evidence_id   TEXT NOT NULL REFERENCES evidence(evidence_id),
    cluster_id              TEXT NOT NULL REFERENCES cluster(cluster_id),
    triggered_by_real_ids   JSONB NOT NULL,              -- ['ev-...', ...]
    retired_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- Reciprocity events (3-event vision metric 측정)
-- ============================================================================

CREATE TABLE reciprocity_event (
    event_id              BIGSERIAL PRIMARY KEY,
    event_type            reciprocity_event_type NOT NULL,
    primary_evidence_id   TEXT NOT NULL REFERENCES evidence(evidence_id),
    related_evidence_ids  JSONB NOT NULL,                -- ['ev-...', ...]
    metadata              JSONB,                          -- 추가 컨텍스트
    origin                evidence_origin NOT NULL,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- Recipe catalog (LLM 초안 + PI Lab 검증된 candidate pool)
-- ============================================================================

CREATE TABLE recipe (
    recipe_id     TEXT PRIMARY KEY,
    family        TEXT NOT NULL,                          -- gradient_boosting/neural/...
    framework     TEXT NOT NULL,                          -- lightgbm/xgboost/torch/...
    description   TEXT NOT NULL,
    metadata      JSONB NOT NULL,                          -- {hyperparam_ranges, strengths}
    source        TEXT NOT NULL DEFAULT 'llm',            -- llm/pilab/community
    verified      BOOLEAN NOT NULL DEFAULT FALSE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- Heuristic rules (cold start fallback)
-- ============================================================================

CREATE TABLE heuristic_rule (
    rule_id      BIGSERIAL PRIMARY KEY,
    name         TEXT NOT NULL UNIQUE,
    condition    JSONB NOT NULL,                          -- 매칭 조건
    candidates   JSONB NOT NULL,                          -- 추천 recipe_id list
    priority     INTEGER NOT NULL DEFAULT 0,
    source       TEXT NOT NULL DEFAULT 'llm',
    verified     BOOLEAN NOT NULL DEFAULT FALSE,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ============================================================================
-- Migration 자체 추적
-- ============================================================================

CREATE TABLE schema_migration (
    filename     TEXT PRIMARY KEY,
    applied_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
