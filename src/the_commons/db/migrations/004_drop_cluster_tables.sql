-- cluster + evidence_cluster: schema-code drift 정리.
-- v0.1은 cluster count를 evidence 테이블 직접 query로 처리 (수만 건 scale 충분).
-- v0.2에 캐싱 필요해지면 그때의 사용 패턴 기반으로 재설계.

-- evidence_cluster 매핑 테이블 (사용 코드 없음)
DROP TABLE IF EXISTS evidence_cluster;

-- cluster cache 테이블 — CASCADE로 retirement_audit의 FK도 함께 정리
DROP TABLE IF EXISTS cluster CASCADE;

-- retirement_audit.cluster_id: 원래 cluster.cluster_id FK였으나
-- 이제 bucket label (e.g. 'tabular-sota_challenge-10k-100k') TEXT 그대로 보관.
-- CASCADE로 FK constraint는 이미 사라졌으므로 타입은 그대로 TEXT 호환.
ALTER TABLE retirement_audit ALTER COLUMN cluster_id TYPE TEXT;
