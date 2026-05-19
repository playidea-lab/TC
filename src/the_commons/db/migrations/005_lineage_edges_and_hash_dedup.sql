-- Migration 005 — lineage_edge 테이블 신규 + content_hash UNIQUE 제거.
--
-- Why:
-- 1) lineage_edge (forward-compat slot, /pi the-commons-lineage-and-hash-fix DD2):
--    vision #7이 약속한 L2 append-only lineage 엣지의 저장소. envelope의
--    `lineage:[{type, target_evidence_id}]` 필드가 여기로 적재된다. v0.1
--    matchmaker는 *읽지 않음* — producer interface(cq M4) 안정화용 예약.
--
-- 2) evidence.content_hash UNIQUE 제거 (DD3, R10 정합):
--    pcq 2.x integrity는 *envelope-독립* — 같은 pcq_record가 다른 evidence_id로
--    두 번 ingest되는 게 합법(R10). 기존 UNIQUE 제약은 R10 위반. evidence_id가
--    유일성 키, content_hash는 무결성 증명일 뿐.

-- ---------------------------------------------------------------------------
-- 1) lineage_edge 테이블
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS lineage_edge (
    edge_id              BIGSERIAL PRIMARY KEY,
    source_evidence_id   TEXT NOT NULL REFERENCES evidence(evidence_id) ON DELETE CASCADE,
    target_evidence_id   TEXT NOT NULL REFERENCES evidence(evidence_id) ON DELETE CASCADE,
    edge_type            TEXT NOT NULL
                         CHECK (edge_type IN ('derives_from','reproduces','contradicts','compared_to')),
    origin               TEXT NOT NULL CHECK (origin IN ('internal','external')),
    metadata             JSONB,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK (source_evidence_id <> target_evidence_id)  -- 자기루프 금지
);

COMMENT ON TABLE lineage_edge IS
    'L2 append-only lineage 엣지 — derives_from·reproduces·contradicts·compared_to. '
    'reciprocity_event(verdict 측정)와 의미 일부 중복(promote≈reproduces-pass), v0.2 통합 결정.';

CREATE INDEX IF NOT EXISTS idx_lineage_edge_source     ON lineage_edge (source_evidence_id);
CREATE INDEX IF NOT EXISTS idx_lineage_edge_target     ON lineage_edge (target_evidence_id);
CREATE INDEX IF NOT EXISTS idx_lineage_edge_type       ON lineage_edge (edge_type);
CREATE INDEX IF NOT EXISTS idx_lineage_edge_created_at ON lineage_edge (created_at DESC);

-- ---------------------------------------------------------------------------
-- 2) evidence.content_hash UNIQUE 제거
-- ---------------------------------------------------------------------------
-- PG가 자동 생성하는 제약 이름은 `<table>_<column>_key` 패턴이지만 환경에 따라 다를 수 있다.
-- DO 블록으로 information_schema에서 동적으로 찾아 DROP — 멱등.
DO $$
DECLARE
    cons_name TEXT;
BEGIN
    SELECT conname INTO cons_name
    FROM pg_constraint
    WHERE conrelid = 'evidence'::regclass
      AND contype = 'u'
      AND pg_get_constraintdef(oid) ILIKE '%content_hash%';

    IF cons_name IS NOT NULL THEN
        EXECUTE format('ALTER TABLE evidence DROP CONSTRAINT %I', cons_name);
    END IF;
END $$;

-- content_hash 검색 성능 위해 (UNIQUE → 일반) 인덱스는 유지/생성.
CREATE INDEX IF NOT EXISTS idx_evidence_content_hash ON evidence (content_hash);
