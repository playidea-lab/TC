"""cost_meter daily budget ceiling 검증 (D.4)."""

from datetime import UTC, datetime, timedelta

import pytest

from the_commons.llm.cost_meter import CostMeter


@pytest.fixture
def meter() -> CostMeter:
    return CostMeter()


def test_today_total_starts_at_zero(meter: CostMeter) -> None:
    """새 meter의 오늘 누적은 0."""
    assert meter.today_total_usd() == 0.0


def test_record_accumulates_today_total(meter: CostMeter) -> None:
    """record 호출이 today_total에 합산."""
    meter.record("gemini-2.5-flash", "rerank", input_tokens=1_000_000, output_tokens=0)
    # gemini-2.5-flash input = $0.30/MTok → 1M tokens = $0.30
    assert meter.today_total_usd() == pytest.approx(0.30)

    meter.record("gemini-embedding-2", "embedding", input_tokens=1_000_000)
    # +$0.10 → $0.40
    assert meter.today_total_usd() == pytest.approx(0.40)


def test_is_over_budget_with_zero_budget_returns_false(meter: CostMeter) -> None:
    """budget=0이면 ceiling 미적용 — 항상 False."""
    meter.record("gemini-2.5-flash", "rerank", input_tokens=10_000_000)
    assert meter.is_over_budget(daily_budget_usd=0.0) is False


def test_is_over_budget_below_budget_returns_false(meter: CostMeter) -> None:
    """budget 미만이면 False."""
    meter.record("gemini-embedding-2", "embedding", input_tokens=100_000)  # ~$0.01
    assert meter.is_over_budget(daily_budget_usd=1.0) is False


def test_is_over_budget_at_or_above_budget_returns_true(meter: CostMeter) -> None:
    """budget 도달·초과면 True."""
    meter.record("gemini-2.5-flash", "rerank", input_tokens=1_000_000)  # $0.30
    assert meter.is_over_budget(daily_budget_usd=0.30) is True
    assert meter.is_over_budget(daily_budget_usd=0.20) is True


def test_today_total_resets_after_utc_midnight(
    meter: CostMeter, monkeypatch: pytest.MonkeyPatch
) -> None:
    """UTC date 변경 시 daily total 자동 reset."""
    # day 1: $0.30 누적
    meter.record("gemini-2.5-flash", "rerank", input_tokens=1_000_000)
    assert meter.today_total_usd() == pytest.approx(0.30)

    # day 2로 시계 이동 — monkeypatch.datetime.now
    fake_tomorrow = datetime.now(UTC) + timedelta(days=1, hours=1)

    class _FakeDatetime:
        @classmethod
        def now(cls, tz=None):  # noqa: ARG003
            return fake_tomorrow

    monkeypatch.setattr("the_commons.llm.cost_meter.datetime", _FakeDatetime)

    # 새 날짜 첫 조회는 0으로 reset
    assert meter.today_total_usd() == 0.0


def test_reset_clears_today_total(meter: CostMeter) -> None:
    """reset() 후 today_total도 0."""
    meter.record("gemini-2.5-flash", "rerank", input_tokens=1_000_000)
    assert meter.today_total_usd() > 0
    meter.reset()
    assert meter.today_total_usd() == 0.0
