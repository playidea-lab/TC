"""TokenBucket + check_and_consume 단위 테스트."""

import time

import pytest
from fastapi import HTTPException

from the_commons.api.rate_limit import TokenBucket, check_and_consume


def test_bucket_allows_up_to_capacity() -> None:
    """burst 한계까지 통과."""
    bucket = TokenBucket(capacity=3, refill_per_sec=0.0001)
    for _ in range(3):
        assert bucket.allow("user-a") is True
    assert bucket.allow("user-a") is False  # 한계 초과


def test_bucket_refills_over_time() -> None:
    """refill 후 다시 통과."""
    bucket = TokenBucket(capacity=2, refill_per_sec=1000.0)
    assert bucket.allow("u") is True
    assert bucket.allow("u") is True
    assert bucket.allow("u") is False
    time.sleep(0.01)  # 10 토큰 회복
    assert bucket.allow("u") is True


def test_bucket_independent_per_key() -> None:
    """다른 key는 독립 카운트."""
    bucket = TokenBucket(capacity=1, refill_per_sec=0.0001)
    assert bucket.allow("user-a") is True
    assert bucket.allow("user-a") is False
    assert bucket.allow("user-b") is True  # b는 영향 없음


def test_check_and_consume_raises_429_when_exhausted() -> None:
    """한계 초과 시 HTTPException 429."""
    bucket = TokenBucket(capacity=1, refill_per_sec=0.0001)
    check_and_consume(bucket, "user-x")  # 첫 호출 통과

    with pytest.raises(HTTPException) as exc_info:
        check_and_consume(bucket, "user-x")

    assert exc_info.value.status_code == 429
    assert "Retry-After" in exc_info.value.headers


def test_bucket_reset_clears_state() -> None:
    """reset() 후 다시 capacity만큼 통과."""
    bucket = TokenBucket(capacity=1, refill_per_sec=0.0001)
    assert bucket.allow("u") is True
    assert bucket.allow("u") is False
    bucket.reset()
    assert bucket.allow("u") is True


@pytest.mark.parametrize(
    ("capacity", "refill"),
    [(0, 1.0), (-1, 1.0), (1, 0.0), (1, -1.0)],
)
def test_bucket_rejects_invalid_construction(capacity: int, refill: float) -> None:
    """잘못된 파라미터는 ValueError."""
    with pytest.raises(ValueError):
        TokenBucket(capacity=capacity, refill_per_sec=refill)
