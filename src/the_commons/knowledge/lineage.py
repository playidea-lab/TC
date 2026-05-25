"""KR1: evidence 계보(derives_from 조상 사슬) 순회.

추세(`trends`)가 "무엇이 좋아졌나"라면 계보는 "어떤 경로로 거기 왔나"(추격 궤적)다.
순수 함수 — evidence list와 시작 id를 받아 조상 체인을 따라간다. LLM·DB 없음, 순환·누락에
안전(방문 집합 + max_depth). evidence 구조(top-level lineage[].target_evidence_id, 노드
요약은 pcq_record.config/metrics)에만 의존.
"""

from __future__ import annotations

from typing import Any

# 계보 깊이 상한 — 순환/비정상 데이터에서 무한 순회 방지
_MAX_DEPTH = 100


def _parent_id(evidence: dict[str, Any]) -> str | None:
    """derives_from 엣지의 부모 evidence_id (없으면 None). lineage는 evidence top-level."""
    for edge in evidence.get("lineage") or []:
        if edge.get("type") == "derives_from":
            return edge.get("target_evidence_id")
    return None


def _node(evidence_id: str, evidence: dict[str, Any], metric: str) -> dict[str, Any]:
    pcq = evidence.get("pcq_record") or {}
    return {
        "evidence_id": evidence_id,
        "recipe_id": (pcq.get("config") or {}).get("recipe_id"),
        "metric": (pcq.get("metrics") or {}).get(metric),
    }


def trace_lineage(
    evidences: list[dict[str, Any]],
    start_id: str,
    *,
    metric: str = "image_auroc",
) -> list[dict[str, Any]]:
    """start_id에서 derives_from 조상 사슬을 따라간 노드 요약 리스트.

    [start, parent, grandparent, ...] 순. 시작 id가 없으면 빈 리스트. 순환은 방문 집합으로
    끊고 _MAX_DEPTH에서 멈춘다.
    """
    by_id = {ev.get("evidence_id"): ev for ev in evidences}
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    current = start_id
    while current and current in by_id and current not in seen and len(chain) < _MAX_DEPTH:
        seen.add(current)
        chain.append(_node(current, by_id[current], metric))
        current = _parent_id(by_id[current])
    return chain
