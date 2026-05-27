"""KR1: evidence 계보(derives_from 조상 사슬) 순회 순수함수 테스트.

추세(무엇이 좋아졌나)를 보완 — 계보는 "어떤 경로로 거기 왔나"(추격 궤적)를 준다.
순수 함수: evidence list + 시작 id → 조상 체인. 순환·누락에 안전.
"""

from the_commons.knowledge.lineage import trace_lineage


def _ev(eid: str, recipe: str, auc: float, parent: str | None = None):
    lineage = [{"type": "derives_from", "target_evidence_id": parent}] if parent else []
    return {
        "evidence_id": eid,
        "lineage": lineage,  # evidence top-level (실제 API 응답 구조)
        "pcq_record": {
            "config": {"recipe_id": recipe},
            "metrics": {"image_auroc": auc},
        },
    }


def test_trace_lineage_follows_derives_from_chain():
    evs = [_ev("r9", "pc", 0.96, "r8"), _ev("r8", "pc", 0.95, "r7"), _ev("r7", "pc", 0.91)]
    chain = trace_lineage(evs, "r9")
    assert [c["evidence_id"] for c in chain] == ["r9", "r8", "r7"]
    assert chain[0]["metric"] == 0.96
    assert chain[-1]["recipe_id"] == "pc"


def test_trace_lineage_missing_start_returns_empty():
    assert trace_lineage([_ev("a", "x", 0.5)], "nope") == []
    assert trace_lineage([], "nope") == []


def test_trace_lineage_breaks_cycle():
    # 순환(a→b→a)이어도 무한 루프 없이 각 노드 1회
    evs = [_ev("a", "x", 0.5, "b"), _ev("b", "x", 0.6, "a")]
    chain = trace_lineage(evs, "a")
    assert [c["evidence_id"] for c in chain] == ["a", "b"]


def test_trace_lineage_stops_at_root():
    # 부모 없는 root에서 멈춤 (lineage 빈 리스트)
    chain = trace_lineage([_ev("only", "x", 0.7)], "only")
    assert [c["evidence_id"] for c in chain] == ["only"]
