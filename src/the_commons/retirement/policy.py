"""retirement 결정 로직 — DB 없이 결정 가능한 pure function들.

Worker는 이 함수들을 호출해 DB 작업을 묶는다.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RetirementCandidate:
    """retire 대상 synthetic + 트리거가 된 real evidence_ids."""

    synthetic_evidence_id: str
    cluster_id: str
    triggered_by_real_ids: list[str]


def should_retire(real_count: int, *, threshold: int) -> bool:
    """cluster의 real evidence가 threshold에 도달했는지."""
    return real_count >= threshold


def select_synthetics_to_retire(
    active_synthetics: list[dict[str, Any]],
    *,
    cluster_id: str,
    triggered_by_real_ids: list[str],
) -> list[RetirementCandidate]:
    """active synthetic 리스트 → retire candidate 리스트.

    Args:
        active_synthetics: deprecated=FALSE인 같은 cluster의 synthetic evidence 목록.
            각 항목은 최소 'evidence_id' 키.
        cluster_id: 해당 cluster의 ID
        triggered_by_real_ids: 임계값을 넘긴 real evidence_id들 (audit log용)
    """
    return [
        RetirementCandidate(
            synthetic_evidence_id=s["evidence_id"],
            cluster_id=cluster_id,
            triggered_by_real_ids=list(triggered_by_real_ids),
        )
        for s in active_synthetics
        if "evidence_id" in s
    ]
