"""이웃 내 min-max metric 정규화 — 이질 target metric → [0,1] 성공도.

retrieved 이웃의 evidence들은 서로 다른 metric·방향을 가질 수 있다.
Beta 사후의 평균 입력으로 쓰려면 비교 가능한 [0,1] 척도가 필요하다.

정규화 규칙 (이번 빌드 고정 — /pi the-commons-infogain-reranker 구현 가정):
- raw 값: intent.expected_baseline['metric']가 metrics에 numeric으로 있으면
  그것을 우선, 없으면 composer._extract_primary_metric 규칙 재사용
  (recipe/metric 추출 규칙 drift 방지).
- min-max: 이웃 raw 값 전체로 [0,1] 스케일.
- 방향: 각 evidence 자신의 intent.tolerance['direction'] 적용
  (기본 higher_is_better; lower_is_better면 1-x). 같은 이웃에 방향이
  섞여도 각자 자기 goal 기준의 "성공도"로 환산되어 비교 가능해진다.
- 경계: numeric metric 결측 → 제외, 이웃 단일값/분모0 → 0.5(중립),
  빈 입력 → {}.

추후 분포기반 등으로 교체 가능하도록 이 모듈 단일 함수로 격리한다.
"""

from __future__ import annotations

from the_commons.library.models import Evidence
from the_commons.matchmaker.composer import _extract_primary_metric

_NEUTRAL = 0.5
_LOWER_IS_BETTER = "lower_is_better"


def _raw_target_value(evidence: Evidence) -> float | None:
    """evidence의 target metric raw 값. 없으면 None (정규화에서 제외)."""
    pcq = evidence.pcq_record
    # intent.expected_baseline.metric 우선 (선언된 target)
    if pcq.intent is not None:
        baseline = pcq.intent.expected_baseline
        if isinstance(baseline, dict):
            name = baseline.get("metric")
            if isinstance(name, str):
                value = pcq.metrics.get(name)
                if isinstance(value, int | float) and not isinstance(value, bool):
                    return float(value)
    # fallback: composer와 동일한 첫 numeric metric 규칙
    primary = _extract_primary_metric(evidence)
    if primary is not None:
        return float(primary["value"])
    return None


def _direction(evidence: Evidence) -> str:
    """intent.tolerance['direction']. 미지정 시 higher_is_better."""
    intent = evidence.pcq_record.intent
    if intent is not None:
        tolerance = intent.tolerance
        if isinstance(tolerance, dict):
            direction = tolerance.get("direction")
            if isinstance(direction, str) and direction:
                return direction
    return "higher_is_better"


def normalize_neighborhood(records: list[Evidence]) -> dict[str, float]:
    """이웃 evidence들을 evidence_id → [0,1] 성공도로 정규화."""
    raw: dict[str, float] = {}
    for ev in records:
        value = _raw_target_value(ev)
        if value is not None:
            raw[ev.evidence_id] = value

    if not raw:
        return {}

    lo = min(raw.values())
    hi = max(raw.values())
    span = hi - lo

    by_id = {ev.evidence_id: ev for ev in records}
    out: dict[str, float] = {}
    for eid, value in raw.items():
        if span == 0.0:
            # 단일값/상수 이웃 — 정보 없음, 방향 무관 중립
            out[eid] = _NEUTRAL
            continue
        scaled = (value - lo) / span  # higher일수록 1.0
        if _direction(by_id[eid]) == _LOWER_IS_BETTER:
            scaled = 1.0 - scaled
        out[eid] = scaled
    return out
