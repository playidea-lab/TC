"""cluster impact 평가 단위 테스트."""

from the_commons.ingestion.cluster_impact import (
    compute_problem_cluster_bucket,
    evaluate_synthetic_match,
)


def _real(metric_value: float, metric_name: str = "AUC") -> dict:
    return {"metrics": {metric_name: metric_value}}


def _synthetic(
    metric_name: str | None = "AUC",
    expected: float | None = 0.85,
    margin: float | None = 0.05,
) -> dict:
    intent = {"goal": "sota_challenge"}
    if metric_name is not None and expected is not None:
        intent["expected_baseline"] = {"metric": metric_name, "value": expected}
    if margin is not None:
        intent["tolerance"] = {"direction": "higher_is_better", "margin": margin}
    return {"intent": intent}


def test_evaluate_promote_when_within_margin() -> None:
    """real metric이 synthetic 예측과 tolerance 내 일치 → promote."""
    result = evaluate_synthetic_match(_real(0.86), _synthetic(expected=0.85, margin=0.05))
    assert result == "promote"


def test_evaluate_contradicts_when_outside_margin() -> None:
    """tolerance 밖 차이 → contradicts."""
    result = evaluate_synthetic_match(_real(0.70), _synthetic(expected=0.85, margin=0.05))
    assert result == "contradicts"


def test_evaluate_indeterminate_when_synthetic_has_no_baseline() -> None:
    """synthetic이 baseline 없으면 비교 불가 → indeterminate."""
    result = evaluate_synthetic_match(
        _real(0.85),
        _synthetic(metric_name=None, expected=None),
    )
    assert result == "indeterminate"


def test_evaluate_indeterminate_when_metric_names_differ() -> None:
    """real이 AUC, synthetic baseline은 F1 → 다른 metric, 비교 불가."""
    result = evaluate_synthetic_match(
        _real(0.85, metric_name="AUC"),
        _synthetic(metric_name="F1", expected=0.80),
    )
    assert result == "indeterminate"


def test_evaluate_uses_default_margin_when_tolerance_missing() -> None:
    """tolerance 미제공 시 DEFAULT_TOLERANCE_MARGIN 적용."""
    # default 0.05, |0.84-0.85|=0.01 → promote
    result = evaluate_synthetic_match(_real(0.84), _synthetic(margin=None))
    assert result == "promote"


def test_evaluate_negative_margin_falls_back_to_default() -> None:
    """음수 margin은 default로 fallback."""
    # margin=-1이 default(0.05)로 → 0.04 차이는 promote
    result = evaluate_synthetic_match(_real(0.81), _synthetic(margin=-1))
    assert result == "promote"


def test_cluster_bucket_format() -> None:
    """`{modality}-{goal}-{band}` 형식."""
    bucket = compute_problem_cluster_bucket(
        {
            "data_fingerprint": {"modality": "tabular", "sample_count_band": "10k-100k"},
            "intent": {"goal": "exploration"},
        }
    )
    assert bucket == "tabular-exploration-10k-100k"


def test_cluster_bucket_handles_missing_fields() -> None:
    """필수 필드 누락 시 'unknown' fallback."""
    bucket = compute_problem_cluster_bucket({})
    assert bucket == "unknown-unknown-unknown"
