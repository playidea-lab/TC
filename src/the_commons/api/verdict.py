"""GET /verdict — 3-event vision metric 현재 상태."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from the_commons.api.dependencies import get_reciprocity_store
from the_commons.auth.dependencies import require_contributor
from the_commons.auth.jwt_verify import VerifiedClaims
from the_commons.reciprocity.event_store import ReciprocityEventStore
from the_commons.reciprocity.verdict_report import build_verdict_report

router = APIRouter(tags=["verdict"])


class VerdictResponse(BaseModel):
    """3개월 vision verdict — success / partial / failure + strengthened."""

    branch: str = Field(description="success | partial | failure")
    is_success: bool
    strengthened: bool = Field(
        description="external origin event ≥ 1 시 True — self-staged 비판 회피"
    )
    counts: dict[str, int] = Field(
        description="event_type별 누적 (loop_closure, promote, contradicts, promote_or_contradict)"
    )
    counts_by_origin: dict[str, int]
    detail: str


@router.get("/verdict", response_model=VerdictResponse)
async def get_verdict(
    claims: VerifiedClaims = Depends(require_contributor),
    reciprocity: ReciprocityEventStore = Depends(get_reciprocity_store),
) -> VerdictResponse:
    """현재 reciprocity event store 누적값으로 verdict 산정.

    3개월 측정 기간 끝에 호출되는 게 본 용도이지만, 언제든 호출 가능 — 현재까지의
    누적 상태를 반환한다.
    """
    _ = claims
    report = await build_verdict_report(reciprocity)
    return VerdictResponse(
        branch=report.branch,
        is_success=report.is_success,
        strengthened=report.strengthened,
        counts=report.counts,
        counts_by_origin=report.counts_by_origin,
        detail=report.detail,
    )
