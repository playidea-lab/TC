"""In-memory token bucket rate limiter.

v0.1엔 single-pod 가정. 분산 운영(Redis backed)은 scale 시 검토.
abuse 방지가 1차 목적 — Gemini 호출 비용 통제.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from threading import Lock

from fastapi import HTTPException, Request, status

from the_commons.auth.jwt_verify import VerifiedClaims
from the_commons.settings import settings


@dataclass
class _BucketState:
    tokens: float
    last_check: float


class TokenBucket:
    """thread-safe token bucket. key는 contributor_id 또는 client IP."""

    def __init__(self, *, capacity: int, refill_per_sec: float) -> None:
        if capacity < 1:
            raise ValueError("capacity ≥ 1")
        if refill_per_sec <= 0:
            raise ValueError("refill_per_sec > 0")
        self._capacity = capacity
        self._refill = refill_per_sec
        self._buckets: dict[str, _BucketState] = {}
        self._lock = Lock()

    def allow(self, key: str) -> bool:
        """1 토큰 차감 시도. 부족하면 False."""
        now = time.monotonic()
        with self._lock:
            state = self._buckets.get(key)
            if state is None:
                state = _BucketState(tokens=self._capacity, last_check=now)
            else:
                elapsed = now - state.last_check
                state.tokens = min(
                    float(self._capacity), state.tokens + elapsed * self._refill
                )
                state.last_check = now

            if state.tokens >= 1:
                state.tokens -= 1
                self._buckets[key] = state
                return True
            self._buckets[key] = state
            return False

    def reset(self) -> None:
        """test용 — 누적 state 초기화."""
        with self._lock:
            self._buckets.clear()


# Endpoint별 별도 bucket. /recommend가 가장 비싸므로 가장 엄격.
recommend_bucket = TokenBucket(capacity=20, refill_per_sec=0.2)  # 20/burst, ~12/min
ingest_bucket = TokenBucket(capacity=30, refill_per_sec=0.5)  # 30/burst, ~30/min


def check_and_consume(bucket: TokenBucket, key: str) -> None:
    """bucket이 막혔으면 429 raise."""
    if not bucket.allow(key):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="rate limit exceeded — try again later",
            headers={"Retry-After": "5"},
        )


def client_rate_key(request: Request, claims: VerifiedClaims) -> str:
    """rate limit key 결정 — contributor_id 우선, 그다음 IP.

    settings.trust_forwarded_for=True면 X-Forwarded-For 첫 항목을 client IP로
    신뢰 (proxy 뒤 production). False면 직접 connection의 client.host만 사용
    (spoofing 방어, single-pod dev).
    """
    if claims.contributor_id:
        return f"contrib:{claims.contributor_id}"

    if settings.trust_forwarded_for:
        xff = request.headers.get("X-Forwarded-For")
        if xff:
            return f"ip:{xff.split(',')[0].strip()}"

    host = request.client.host if request.client else "unknown"
    return f"ip:{host}"
