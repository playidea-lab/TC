"""LLM 호출 비용을 추적하는 cost meter.

모든 외부 API 호출이 여기를 거쳐 token 사용량·비용을 누적한다.
v0.1엔 in-memory tracking, v0.2엔 DB로 영구화 검토.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from threading import Lock

# Gemini 가격 (USD per 1M tokens, 2026-05 기준)
PRICING_USD_PER_M_TOKEN: dict[str, dict[str, float]] = {
    "gemini-embedding-2": {"input": 0.10, "output": 0.0},
    "gemini-2.5-flash": {"input": 0.30, "output": 2.50},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    # 추가 모델은 여기에 등록
}

TOKENS_PER_MILLION = 1_000_000


@dataclass(frozen=True)
class CostEntry:
    """단일 호출 기록."""

    model: str
    operation: str  # 'embedding' | 'rerank' | ...
    input_tokens: int
    output_tokens: int
    cost_usd: float
    timestamp: datetime


@dataclass
class CostSummary:
    """집계 결과."""

    total_calls: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost_usd: float = 0.0
    by_model: dict[str, float] = field(default_factory=dict)
    by_operation: dict[str, float] = field(default_factory=dict)


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """모델 가격표에서 비용 계산. 미등록 모델은 0 반환 + 로깅 권장."""
    pricing = PRICING_USD_PER_M_TOKEN.get(model)
    if pricing is None:
        return 0.0
    input_cost = (input_tokens / TOKENS_PER_MILLION) * pricing["input"]
    output_cost = (output_tokens / TOKENS_PER_MILLION) * pricing["output"]
    return input_cost + output_cost


class CostMeter:
    """thread-safe 누적 cost tracker + daily budget ceiling.

    모든 LLM provider 구현체가 호출 후 record()를 통해 사용량을 보고한다.
    daily budget 도달 시 is_over_budget()가 True — endpoint가 호출 차단.
    """

    def __init__(self) -> None:
        self._entries: list[CostEntry] = []
        self._lock = Lock()
        self._today_total_usd: float = 0.0
        self._today_date: date = datetime.now(UTC).date()

    def record(
        self,
        model: str,
        operation: str,
        input_tokens: int,
        output_tokens: int = 0,
    ) -> CostEntry:
        """호출 1건 기록. 누적 entry를 반환. UTC date 변경 시 daily total reset."""
        cost = estimate_cost_usd(model, input_tokens, output_tokens)
        now = datetime.now(UTC)
        entry = CostEntry(
            model=model,
            operation=operation,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            timestamp=now,
        )
        with self._lock:
            self._entries.append(entry)
            today = now.date()
            if today != self._today_date:
                self._today_total_usd = 0.0
                self._today_date = today
            self._today_total_usd += cost
        return entry

    def today_total_usd(self) -> float:
        """오늘(UTC) 누적 비용. 자정 지나면 자동 reset."""
        now = datetime.now(UTC).date()
        with self._lock:
            if now != self._today_date:
                # rollover — 새 날짜의 첫 조회는 0
                self._today_total_usd = 0.0
                self._today_date = now
            return self._today_total_usd

    def is_over_budget(self, daily_budget_usd: float) -> bool:
        """daily_budget_usd ≥ 오늘 누적이면 True. budget=0이면 ceiling 미적용."""
        if daily_budget_usd <= 0:
            return False
        return self.today_total_usd() >= daily_budget_usd

    def summary(self) -> CostSummary:
        """누적 사용량을 모델·operation별로 집계."""
        with self._lock:
            entries = list(self._entries)

        result = CostSummary()
        by_model: dict[str, float] = defaultdict(float)
        by_op: dict[str, float] = defaultdict(float)
        for e in entries:
            result.total_calls += 1
            result.total_input_tokens += e.input_tokens
            result.total_output_tokens += e.output_tokens
            result.total_cost_usd += e.cost_usd
            by_model[e.model] += e.cost_usd
            by_op[e.operation] += e.cost_usd
        result.by_model = dict(by_model)
        result.by_operation = dict(by_op)
        return result

    def reset(self) -> None:
        """누적 데이터 초기화 — 테스트·새 측정 기간 시작 시 사용."""
        with self._lock:
            self._entries.clear()
            self._today_total_usd = 0.0
            self._today_date = datetime.now(UTC).date()


# 모듈 전역 인스턴스. 모든 provider가 동일 meter를 공유.
meter = CostMeter()
