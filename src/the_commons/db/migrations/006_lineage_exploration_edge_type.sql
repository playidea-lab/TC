-- 006: lineage_edge.edge_type에 'exploration' 추가
-- ---------------------------------------------------------------------------
-- cq-tc-autonomous-experiment-loop v1: ε-novelty mix의 explore 분기에서 wild card
-- recipe를 시도할 때 best_so_far evidence와의 lineage edge를 'exploration' 타입으로
-- 박는다. 005의 CHECK constraint는 4개 타입만 허용했으므로 교체한다.
-- (models.py LineageEdgeType과 정합 — DB CHECK와 Pydantic Literal 둘 다 갱신 필요.)

ALTER TABLE lineage_edge DROP CONSTRAINT IF EXISTS lineage_edge_edge_type_check;

ALTER TABLE lineage_edge ADD CONSTRAINT lineage_edge_edge_type_check
    CHECK (edge_type IN ('derives_from','reproduces','contradicts','compared_to','exploration'));

COMMENT ON TABLE lineage_edge IS
    'L2 append-only lineage 엣지 — derives_from·reproduces·contradicts·compared_to·exploration. '
    'exploration = ε-novelty mix wild card 분기점. '
    'reciprocity_event(verdict 측정)와 의미 일부 중복(promote≈reproduces-pass), v0.2 통합 결정.';
