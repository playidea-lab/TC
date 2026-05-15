"""GET /metrics — 운영 가시성 endpoint.

cost meter + reciprocity event count를 단일 JSON으로. v0.1엔 직접 노출,
v0.2에 Prometheus exporter 또는 외부 dashboard 연동.

JWT 필요 (다른 endpoint와 동일 보호 layer).
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from the_commons import __version__
from the_commons.api.dependencies import get_reciprocity_store
from the_commons.auth.dependencies import require_contributor
from the_commons.auth.jwt_verify import VerifiedClaims
from the_commons.llm.cost_meter import meter
from the_commons.reciprocity.event_store import ReciprocityEventStore

router = APIRouter(tags=["metrics"])


class CostMetrics(BaseModel):
    today_usd: float = Field(description="UTC 오늘 누적 LLM 비용 (USD)")
    total_calls: int
    total_input_tokens: int
    total_output_tokens: int
    total_usd: float
    by_model: dict[str, float]
    by_operation: dict[str, float]


class MetricsResponse(BaseModel):
    """v0.1 직접 노출. v0.2엔 Prometheus 형식 별도 endpoint."""

    version: str
    cost: CostMetrics
    events_by_type: dict[str, int] = Field(
        description="loop_closure / promote / contradicts 각각의 누적 카운트"
    )


@router.get("/metrics", response_model=MetricsResponse)
async def get_metrics(
    claims: VerifiedClaims = Depends(require_contributor),
    reciprocity: ReciprocityEventStore = Depends(get_reciprocity_store),
) -> MetricsResponse:
    """cost meter + reciprocity event count 종합 응답."""
    _ = claims
    summary = meter.summary()
    by_type = await reciprocity.count_by_type()

    return MetricsResponse(
        version=__version__,
        cost=CostMetrics(
            today_usd=meter.today_total_usd(),
            total_calls=summary.total_calls,
            total_input_tokens=summary.total_input_tokens,
            total_output_tokens=summary.total_output_tokens,
            total_usd=summary.total_cost_usd,
            by_model=summary.by_model,
            by_operation=summary.by_operation,
        ),
        events_by_type=dict(by_type),
    )
