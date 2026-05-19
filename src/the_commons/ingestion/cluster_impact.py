"""cluster impact 평가 — real evidence가 synthetic의 예측을 검증한 결과 분류.

새 real evidence가 들어왔을 때:
- 같은 (problem-cluster, recipe) 영역의 synthetic을 promote / contradicts로 분류
- 결과는 reciprocity_event 테이블에 기록되고 retirement worker가 활용

비교는 *primary metric*과 *tolerance*에 의존. tolerance 미제공 시 default 사용.
"""

from typing import Any, Literal

DEFAULT_TOLERANCE_MARGIN = 0.05

MatchOutcome = Literal["promote", "contradicts", "indeterminate"]


def _pcq(record: dict[str, Any]) -> dict[str, Any]:
    """envelope record → pcq_record dict (envelope 미사용 시 record 자체)."""
    inner = record.get("pcq_record")
    return inner if isinstance(inner, dict) else record


def evaluate_synthetic_match(
    real_record: dict[str, Any],
    synthetic_record: dict[str, Any],
) -> MatchOutcome:
    """real evidence가 synthetic의 expected_baseline을 검증한 결과.

    envelope 또는 raw pcq_record 둘 다 수용. 반환:
        promote — real metric이 synthetic 예측과 tolerance 내 일치
        contradicts — tolerance 밖 차이
        indeterminate — metric 이름 다름·tolerance 없고 baseline 없음 등
    """
    real_pcq = _pcq(real_record)
    synth_pcq = _pcq(synthetic_record)
    real_metrics = real_pcq.get("metrics") or {}
    synth_intent = synth_pcq.get("intent") or {}
    expected = synth_intent.get("expected_baseline") or {}

    metric_name = expected.get("metric")
    expected_value = expected.get("value")

    if not metric_name or expected_value is None:
        return "indeterminate"

    actual_value = real_metrics.get(metric_name)
    if not isinstance(actual_value, int | float):
        return "indeterminate"

    tolerance = synth_intent.get("tolerance") or {}
    margin = tolerance.get("margin", DEFAULT_TOLERANCE_MARGIN)
    if not isinstance(margin, int | float) or margin < 0:
        margin = DEFAULT_TOLERANCE_MARGIN

    if abs(actual_value - expected_value) <= margin:
        return "promote"
    return "contradicts"


def compute_problem_cluster_bucket(record: dict[str, Any]) -> str:
    """evidence를 클러스터 bucket key로 매핑.

    같은 bucket = 같은 problem 영역. cluster table의 problem_fingerprint_bucket
    컬럼에 들어가는 값.

    형식: `<modality>-<intent_goal>-<sample_count_band>`
    """
    pcq = _pcq(record)
    fingerprint = pcq.get("data_fingerprint") or {}
    intent = pcq.get("intent") or {}

    modality = fingerprint.get("modality") or "unknown"
    band = fingerprint.get("sample_count_band") or "unknown"
    goal = intent.get("goal") or "unknown"

    return f"{modality}-{goal}-{band}"
