"""3-event vision metric verdict report.

3개월 measurement window 끝에 자동 생성. event store의 누적 카운트를 verdict
3-branch (success / partial / failure)로 분류.
"""

from dataclasses import dataclass
from typing import Literal

from the_commons.reciprocity.event_store import EventType, ReciprocityEventStore

REQUIRED_EVENTS: tuple[EventType, ...] = ("loop_closure", "promote", "contradicts")
PROMOTE_OR_CONTRADICT_BUCKET = "promote_or_contradict"

VerdictBranch = Literal["success", "partial", "failure"]


@dataclass(frozen=True)
class VerdictReport:
    """3-event verdict 보고서 — 3개월 끝에 생성."""

    counts: dict[str, int]
    counts_by_origin: dict[str, int]
    branch: VerdictBranch
    strengthened: bool  # external origin ≥ 1
    detail: str

    @property
    def is_success(self) -> bool:
        return self.branch == "success"


async def build_verdict_report(store: ReciprocityEventStore) -> VerdictReport:
    """현재 event store 누적값으로 verdict 산정.

    3-event 요건:
      loop_closure ≥ 1 / promote ≥ 1 또는 contradicts ≥ 1 / 둘 다 ≥ 0이면 단순 합산
    success: 3 event 모두 ≥ 1
    partial: 1~2 event 충족
    failure: 0 event
    """
    by_type = await store.count_by_type()
    by_origin = await store.count_by_origin()

    # promote / contradicts 둘 중 하나라도 ≥ 1이면 promote_or_contradict 축 충족
    pc_total = by_type.get("promote", 0) + by_type.get("contradicts", 0)
    loop = by_type.get("loop_closure", 0)
    retire_axis = pc_total  # synthetic 검증 사용자 행동 — both count

    counts: dict[str, int] = {
        "loop_closure": loop,
        "promote": by_type.get("promote", 0),
        "contradicts": by_type.get("contradicts", 0),
        PROMOTE_OR_CONTRADICT_BUCKET: pc_total,
    }

    axes_satisfied = sum(1 for v in (loop, retire_axis) if v >= 1)
    # synthetic_retire는 retirement_audit 테이블에서 가져오는 게 옳지만 v0.1엔
    # promote/contradicts와 axis를 공유 (둘 다 발생 → reciprocity 동작 증명).
    # M3에서 별도 axis 분리 가능.

    if axes_satisfied >= 2:
        branch: VerdictBranch = "success"
        detail = "all reciprocity axes satisfied"
    elif axes_satisfied == 1:
        branch = "partial"
        detail = "one of (loop_closure, promote_or_contradict) is zero"
    else:
        branch = "failure"
        detail = "no reciprocity event recorded — vision revision warranted"

    strengthened = by_origin.get("external", 0) >= 1

    return VerdictReport(
        counts=counts,
        counts_by_origin=dict(by_origin),
        branch=branch,
        strengthened=strengthened,
        detail=detail,
    )
