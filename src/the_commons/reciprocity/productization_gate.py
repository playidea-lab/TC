"""서비스화 게이트 — TC를 cq-only Phase-1 → 독립 서비스로 플립하는 신호.

bare verdict보다 *높은* 별개 바: 세 조건 동시 충족 시에만 트립.
  C1 강화된 성공  : verdict 성공 ∧ external-origin ≥ 1 (기존 verdict 재사용)
  C2 코퍼스 밀도  : 추천 코퍼스가 real 우세 (synthetic-dominant 아님)
  C3 추천 품질    : 재현 promote-rate proxy ≥ 바닥 (최소 재현 N 위에서)

거짓 통과 금지: C3 임계 미설정 또는 재현 N 미달이면 None("측정 불가")이며
None은 트립을 막는다. 게이트 트립은 *신호*이지 자동 외부개방·플립이 아니다
(owner 명시 결정). 미트립 시 조건별 진단을 내고, 경계 window 수 연속
미트립이면 강제 재결정 요구를 표기한다 (게이트는 escape가 없으면 새장).
(/pi the-commons-productization-gate)
"""

from __future__ import annotations

from dataclasses import dataclass

from the_commons.library.store import EvidenceStore
from the_commons.reciprocity.verdict_report import VerdictReport
from the_commons.settings import settings


@dataclass(frozen=True)
class ProductizationGate:
    """서비스화 게이트 산정 결과. /verdict 응답에 그대로 노출."""

    c1_strengthened_success: bool
    c2_corpus_density: bool | None  # None = 산정 불가
    c3_quality: bool | None  # None = 측정 불가 (거짓 통과 금지)
    tripped: bool
    diagnostic: str
    forced_decision: str | None


async def _corpus_density(store: EvidenceStore) -> bool | None:
    """real 우세 여부. 표본이 임계 미만이면 None(산정 불가)."""
    _, real_total = await store.list_evidence(tier="real", limit=1)
    _, syn_total = await store.list_evidence(tier="synthetic", limit=1)
    total = real_total + syn_total
    # 밀도를 판단할 최소 표본 — retirement 임계 재사용 (새 상수 회피)
    if total < settings.retirement_real_threshold:
        return None
    return real_total > syn_total


def _quality_proxy(verdict: VerdictReport) -> bool | None:
    """재현 promote-rate proxy. 미설정/소표본이면 None(측정 불가)."""
    floor = settings.productization_promote_rate_floor
    if floor < 0.0:  # sentinel: 미설정
        return None
    promote = verdict.counts.get("promote", 0)
    contradicts = verdict.counts.get("contradicts", 0)
    reproductions = promote + contradicts
    if reproductions < settings.productization_min_reproductions:
        return None
    if reproductions == 0:
        return None
    return (promote / reproductions) >= floor


async def build_productization_gate(
    verdict: VerdictReport,
    evidence_store: EvidenceStore,
    *,
    consecutive_untripped_windows: int = 0,
) -> ProductizationGate:
    """verdict + 코퍼스 상태로 서비스화 게이트 산정."""
    c1 = verdict.is_success and verdict.strengthened
    c2 = await _corpus_density(evidence_store)
    c3 = _quality_proxy(verdict)

    tripped = c1 and c2 is True and c3 is True

    reasons: list[str] = []
    if not c1:
        reasons.append(
            "C1 미충족 — 강화된 성공 아님 "
            f"(success={verdict.is_success}, external≥1={verdict.strengthened})"
        )
    if c2 is None:
        reasons.append("C2 산정 불가 — 코퍼스 표본 부족")
    elif c2 is False:
        reasons.append("C2 미충족 — synthetic 우세 (real-dominant 아님)")
    if c3 is None:
        reasons.append("C3 측정 불가 — promote-rate 임계 미설정 또는 재현 부족")
    elif c3 is False:
        reasons.append("C3 미충족 — 재현 promote-rate가 바닥 미만")
    diagnostic = "게이트 통과 (신호 — 플립은 owner 결정)" if tripped else "; ".join(
        reasons
    )

    forced_decision: str | None = None
    escape = settings.productization_gate_escape_windows
    if escape > 0 and consecutive_untripped_windows >= escape:
        forced_decision = (
            f"재결정 요구 — {consecutive_untripped_windows} window 연속 미트립: "
            "연장 / 바 하향+근거 / 피벗 / 종료 중 택1"
        )

    return ProductizationGate(
        c1_strengthened_success=c1,
        c2_corpus_density=c2,
        c3_quality=c3,
        tripped=tripped,
        diagnostic=diagnostic,
        forced_decision=forced_decision,
    )
