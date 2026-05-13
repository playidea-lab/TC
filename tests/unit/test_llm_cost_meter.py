"""cost_meter — 누적 집계 + 가격표 정합 검증."""

import pytest

from the_commons.llm.cost_meter import (
    PRICING_USD_PER_M_TOKEN,
    CostMeter,
    estimate_cost_usd,
)


@pytest.fixture
def fresh_meter() -> CostMeter:
    """매 테스트 새 meter 인스턴스."""
    return CostMeter()


def test_estimate_cost_with_known_model_returns_proportional_cost() -> None:
    """등록된 모델은 token 수에 비례해 비용 계산."""
    cost = estimate_cost_usd("gemini-2.5-flash", input_tokens=1_000_000, output_tokens=0)
    assert cost == pytest.approx(0.30)

    cost = estimate_cost_usd("gemini-2.5-flash", input_tokens=0, output_tokens=1_000_000)
    assert cost == pytest.approx(2.50)


def test_estimate_cost_with_unknown_model_returns_zero() -> None:
    """등록 안 된 모델은 0 반환 (silent fallback)."""
    cost = estimate_cost_usd("unknown-model", input_tokens=1000, output_tokens=1000)
    assert cost == 0.0


def test_record_accumulates_entries(fresh_meter: CostMeter) -> None:
    """record 호출 시 누적 entry 생성."""
    fresh_meter.record("gemini-embedding-2", "embedding", input_tokens=10_000)
    fresh_meter.record(
        "gemini-2.5-flash", "rerank", input_tokens=5_000, output_tokens=500
    )

    summary = fresh_meter.summary()
    assert summary.total_calls == 2
    assert summary.total_input_tokens == 15_000
    assert summary.total_output_tokens == 500
    assert summary.total_cost_usd > 0


def test_summary_groups_by_model_and_operation(fresh_meter: CostMeter) -> None:
    """집계가 model/operation 차원으로 분리되어야 한다."""
    fresh_meter.record("gemini-embedding-2", "embedding", input_tokens=100_000)
    fresh_meter.record("gemini-2.5-flash", "rerank", input_tokens=10_000, output_tokens=1_000)

    summary = fresh_meter.summary()
    assert "gemini-embedding-2" in summary.by_model
    assert "gemini-2.5-flash" in summary.by_model
    assert "embedding" in summary.by_operation
    assert "rerank" in summary.by_operation


def test_reset_clears_all_entries(fresh_meter: CostMeter) -> None:
    """reset은 누적된 entry를 완전히 제거해야 한다."""
    fresh_meter.record("gemini-2.5-flash", "rerank", input_tokens=1_000, output_tokens=100)
    assert fresh_meter.summary().total_calls == 1

    fresh_meter.reset()
    assert fresh_meter.summary().total_calls == 0
    assert fresh_meter.summary().total_cost_usd == 0.0


def test_pricing_table_has_required_models() -> None:
    """v0.1 stack에 필요한 모델 가격이 등록되어 있어야 한다."""
    assert "gemini-embedding-2" in PRICING_USD_PER_M_TOKEN
    assert "gemini-2.5-flash" in PRICING_USD_PER_M_TOKEN
    for model_pricing in PRICING_USD_PER_M_TOKEN.values():
        assert "input" in model_pricing
        assert "output" in model_pricing
