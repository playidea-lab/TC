"""infogain.normalize — 이웃 내 min-max 정규화 + intent.direction 반영 단위 테스트."""

from datetime import UTC, datetime

from the_commons.library.models import Evidence
from the_commons.matchmaker.infogain.normalize import normalize_neighborhood


def _evidence(
    eid: str,
    *,
    metrics: dict,
    direction: str | None = None,
    expected_metric: str | None = None,
) -> Evidence:
    tolerance = {"direction": direction} if direction else None
    expected_baseline = {"metric": expected_metric} if expected_metric else None
    rec = {
        "evidence_id": eid,
        "tier": "real",
        "outreach_origin": "external",
        "synthetic_source": None,
        "pcq_record": {
            "intent": {
                "goal": "exploration",
                "expected_baseline": expected_baseline,
                "tolerance": tolerance,
            },
            "data_fingerprint": {
                "modality": "tabular",
                "sample_count_band": "10k-100k",
            },
            "config": {"recipe_id": "r"},
            "metrics": metrics,
            "worker_spec": {"cpu_cores": 8, "ram_gb": 16},
            "attribution": {"operator": None},
            "contract_version": "2.0",
        },
    }
    return Evidence.model_validate(rec)


def test_normalize_empty_input_returns_empty_dict() -> None:
    assert normalize_neighborhood([]) == {}


def test_higher_is_better_maps_max_to_one_min_to_zero() -> None:
    recs = [
        _evidence("a", metrics={"AUC": 0.9}, direction="higher_is_better"),
        _evidence("b", metrics={"AUC": 0.5}, direction="higher_is_better"),
        _evidence("c", metrics={"AUC": 0.7}, direction="higher_is_better"),
    ]
    out = normalize_neighborhood(recs)
    assert out["a"] == 1.0
    assert out["b"] == 0.0
    assert 0.0 < out["c"] < 1.0


def test_lower_is_better_inverts_scale() -> None:
    recs = [
        _evidence("a", metrics={"loss": 0.1}, direction="lower_is_better"),
        _evidence("b", metrics={"loss": 0.9}, direction="lower_is_better"),
    ]
    out = normalize_neighborhood(recs)
    # 가장 낮은 loss(a)가 성공도 1.0, 가장 높은 loss(b)가 0.0
    assert out["a"] == 1.0
    assert out["b"] == 0.0


def test_default_direction_is_higher_is_better() -> None:
    recs = [
        _evidence("a", metrics={"AUC": 1.0}),
        _evidence("b", metrics={"AUC": 0.0}),
    ]
    out = normalize_neighborhood(recs)
    assert out["a"] == 1.0
    assert out["b"] == 0.0


def test_single_value_or_constant_neighborhood_is_neutral_half() -> None:
    recs = [
        _evidence("a", metrics={"AUC": 0.8}, direction="higher_is_better"),
        _evidence("b", metrics={"AUC": 0.8}, direction="lower_is_better"),
    ]
    out = normalize_neighborhood(recs)
    # max==min → 분모 0 → 방향 무관 0.5 중립
    assert out["a"] == 0.5
    assert out["b"] == 0.5


def test_missing_numeric_metric_is_excluded() -> None:
    recs = [
        _evidence("a", metrics={"AUC": 0.9}),
        _evidence("b", metrics={"note": "no-numeric"}),
    ]
    out = normalize_neighborhood(recs)
    assert "b" not in out
    assert "a" in out


def test_expected_baseline_metric_preferred_over_first_numeric() -> None:
    # 첫 numeric은 latency지만 intent.expected_baseline.metric=AUC → AUC 사용
    recs = [
        _evidence(
            "a",
            metrics={"latency": 10.0, "AUC": 0.9},
            direction="higher_is_better",
            expected_metric="AUC",
        ),
        _evidence(
            "b",
            metrics={"latency": 99.0, "AUC": 0.1},
            direction="higher_is_better",
            expected_metric="AUC",
        ),
    ]
    out = normalize_neighborhood(recs)
    # AUC 기준이면 a가 우세(1.0). latency 기준이었다면 a가 0.0이 됐을 것.
    assert out["a"] == 1.0
    assert out["b"] == 0.0
