"""GET /verdict — 3-event vision metric 현재 상태."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from the_commons.api.dependencies import get_evidence_store, get_reciprocity_store
from the_commons.auth.dependencies import require_contributor
from the_commons.auth.jwt_verify import VerifiedClaims
from the_commons.library.store import EvidenceStore
from the_commons.reciprocity.event_store import ReciprocityEventStore
from the_commons.reciprocity.productization_gate import build_productization_gate
from the_commons.reciprocity.verdict_report import build_verdict_report

router = APIRouter(tags=["verdict"])


class ProductizationGateOut(BaseModel):
    """서비스화 게이트 신호 — tripped는 *신호*이지 자동 플립 아님(owner 결정)."""

    c1_strengthened_success: bool
    c2_corpus_density: bool | None = Field(
        description="None = 코퍼스 표본 부족, 산정 불가"
    )
    c3_quality: bool | None = Field(
        description="None = promote-rate 임계 미설정 또는 재현 부족, 측정 불가"
    )
    tripped: bool
    diagnostic: str
    forced_decision: str | None


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
    productization_gate: ProductizationGateOut


@router.get("/verdict", response_model=VerdictResponse)
async def get_verdict(
    claims: VerifiedClaims = Depends(require_contributor),
    reciprocity: ReciprocityEventStore = Depends(get_reciprocity_store),
    evidence_store: EvidenceStore = Depends(get_evidence_store),
) -> VerdictResponse:
    """현재 reciprocity event store 누적값으로 verdict + 서비스화 게이트 산정.

    3개월 측정 기간 끝에 호출되는 게 본 용도이지만, 언제든 호출 가능 — 현재까지의
    누적 상태를 반환한다. 게이트 tripped는 *신호*이며 플립은 owner 결정.
    """
    _ = claims
    report = await build_verdict_report(reciprocity)
    # consecutive_untripped_windows는 window 이력 영속이 v0.1 범위 외 →
    # 0 고정 (강제 재결정은 settings.productization_gate_escape_windows>0 +
    # 외부 cron이 누적 카운트를 주입할 때 활성. v0.1 단발 조회는 0).
    gate = await build_productization_gate(
        report, evidence_store, consecutive_untripped_windows=0
    )
    return VerdictResponse(
        branch=report.branch,
        is_success=report.is_success,
        strengthened=report.strengthened,
        counts=report.counts,
        counts_by_origin=report.counts_by_origin,
        detail=report.detail,
        productization_gate=ProductizationGateOut(
            c1_strengthened_success=gate.c1_strengthened_success,
            c2_corpus_density=gate.c2_corpus_density,
            c3_quality=gate.c3_quality,
            tripped=gate.tripped,
            diagnostic=gate.diagnostic,
            forced_decision=gate.forced_decision,
        ),
    )
