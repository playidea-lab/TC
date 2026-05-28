"""MCP 도구 — explore-loop QD 컨트롤러를 에이전트(Claude Code)가 호출하는 인터페이스.

R1 Phase C1. 4개 도구:
  - tc_explore_recommend_action(profile, ...): 컨트롤러가 다음 행동(모드+부모+타깃셀) 추천
  - tc_explore_report_result(profile, action, fitness): 에이전트가 평가 결과 보고 → placement
  - tc_explore_archive_state(profile): 현재 archive 스냅샷
  - tc_explore_build_query(profile): Explosion 모드 웹검색 쿼리 합성(스텁, D-phase에서 본격화)

설계: 각 도구는 ExploreSession을 매 호출마다 load→step/report→save한다(stateless 호출,
state는 디스크). 정책 결정(3-E 비율, stagnation 감지)은 컨트롤러 내부. attribution(V12)은
report 시점에 JSONL append.

core(_*_impl) 함수는 FastMCP 의존 없이 단위 테스트 가능. @mcp.tool() 래퍼는 register()에서.
"""

from __future__ import annotations

from typing import Any

from the_commons.exploration.session import (
    ExploreSession, action_from_dict, action_to_dict,
)


def _recommend_action_impl(
    profile: str, *, epsilon: float = 0.4, budget: int = 30,
    seed_base: int | None = None, tasks: list[str] | None = None,
    max_wallclock_seconds: int | None = None,
    max_explosion_rounds: int | None = None,
    max_total_rounds: int | None = None,
) -> dict[str, Any]:
    """컨트롤러가 다음 행동을 추천한다(3-E 모드 + 부모 elite + 타깃 셀).

    V10 caps: 위반 시 mode='stop' action을 즉시 반환(컨트롤러 step() 호출 전).
    None cap은 무제한. 호출자(에이전트)가 매 라운드 caps 넘겨 자율 종료 트리거.
    """
    s = ExploreSession(profile, epsilon=epsilon, budget=budget,
                       seed_base=seed_base, tasks=tasks)
    cap_reason = s.check_caps(
        max_wallclock_seconds=max_wallclock_seconds,
        max_explosion_rounds=max_explosion_rounds,
        max_total_rounds=max_total_rounds,
    )
    if cap_reason:
        # V10 stop emit — 컨트롤러 step 건너뜀, archive 갱신 없음
        return {"mode": "stop", "task": "", "genotype": None,
                "descriptor": [-1, -1], "seed": 0, "target": "elite",
                "reason": cap_reason}
    action = s.controller.step()
    s.save()
    return action_to_dict(action)


def _report_result_impl(
    profile: str, action: dict[str, Any], fitness: float,
    *, code: str = "", stderr_tail: str = "", attribution: dict | None = None,
) -> dict[str, Any]:
    """에이전트가 평가 결과를 보고 → 컨트롤러 placement.

    fitness는 max convention (낮을수록 좋은 metric은 caller가 부호 반전).
    code/stderr_tail/attribution은 V12 attribution log 입력(forensic 디버그용).
    """
    s = ExploreSession(profile)
    act = action_from_dict(action)
    s.controller.report(act, float(fitness))
    # V10: explosion 모드 카운터 누적 (cap 검사 입력)
    if act.kind == "explosion":
        s.increment_explosion_rounds()
    s.save()
    # V12 attribution
    s.log_attribution({
        "round": s.controller.round, "action": action, "fitness": float(fitness),
        "code_len": len(code), "stderr_tail": stderr_tail[:1000] if stderr_tail else "",
        "attribution": attribution or {},
    })
    return {"ok": True, "round": s.controller.round,
            "n_cells": len(s.controller.archive),
            "universals": list(s.controller.universals)}


def _archive_state_impl(profile: str) -> dict[str, Any]:
    """현재 archive 스냅샷 — 에이전트가 진행 상황 점검·요약 보고에 사용."""
    s = ExploreSession(profile)
    snap = s.archive_snapshot()
    # 큰 archive 압축: 셀별로 elite·mean·n만 (samples 전체는 안 보냄)
    cells = {}
    for key, cell in snap["archive"].items():
        samples = cell.get("samples", [])
        cells[key] = {
            "descriptor": cell["descriptor"],
            "elite": cell.get("elite"),
            "n_samples": len(samples),
            "mean": sum(samples) / len(samples) if samples else None,
        }
    return {
        "profile": profile, "round": snap["round"], "budget": snap["budget"],
        "n_cells": snap["n_cells"], "cells": cells,
        "universals": snap.get("universals", []),
    }


def _build_query_impl(profile: str) -> dict[str, Any]:
    """Explosion 모드 웹검색 쿼리 합성. (Phase D 본격 구현 전 placeholder)

    현 archive의 stagnation 컨텍스트를 자연어 쿼리로 변환할 예정.
    """
    s = ExploreSession(profile)
    snap = s.archive_snapshot()
    # 가장 좋은 score + 가장 빈 셀 영역으로 단순 쿼리 합성(placeholder)
    best = None
    for cell in snap["archive"].values():
        samples = cell.get("samples", [])
        if samples:
            m = sum(samples) / len(samples)
            if best is None or m > best:
                best = m
    return {
        "profile": profile,
        "query": (f"{profile} state-of-the-art techniques beyond current best score "
                  f"{best:.4f}" if best is not None else f"{profile} latest techniques"),
        "stagnation_round_count": 0,  # TODO Phase D: real stagnation detection
        "note": "placeholder — Phase D에서 archive 기반 쿼리 합성 본격화",
    }


def register(mcp) -> None:
    """FastMCP 인스턴스에 tc_explore_* 도구 4개 등록. server.py에서 호출."""

    @mcp.tool()
    def tc_explore_recommend_action(
        profile: str, epsilon: float = 0.4, budget: int = 30,
        seed_base: int | None = None, tasks: list[str] | None = None,
        max_wallclock_seconds: int | None = None,
        max_explosion_rounds: int | None = None,
        max_total_rounds: int | None = None,
    ) -> dict[str, Any]:
        """QD 컨트롤러가 다음 라운드의 행동을 추천한다.

        Args:
          profile: experiments/<profile>/profile.py가 있어야 함.
          epsilon, budget, seed_base, tasks: cold start 시(state 없을 때)만 사용.
          max_wallclock_seconds, max_explosion_rounds, max_total_rounds:
            V10 운영 cap. 위반 시 mode='stop' action 즉시 반환(컨트롤러 안 굴림).
            None=무제한. 호출자가 매 라운드 동일하게 넘기는 게 안전.

        Returns:
          {mode, task, genotype, descriptor, seed, target, reason}
          mode='stop'이면 reason에 cap 사유.
        """
        return _recommend_action_impl(
            profile, epsilon=epsilon, budget=budget,
            seed_base=seed_base, tasks=tasks,
            max_wallclock_seconds=max_wallclock_seconds,
            max_explosion_rounds=max_explosion_rounds,
            max_total_rounds=max_total_rounds,
        )

    @mcp.tool()
    def tc_explore_report_result(
        profile: str, action: dict[str, Any], fitness: float,
        code: str = "", stderr_tail: str = "", attribution: dict | None = None,
    ) -> dict[str, Any]:
        """평가 결과를 컨트롤러에 보고 → placement + attribution 영속.

        fitness는 max convention. min metric(bpb)은 caller가 부호 반전(-bpb)해 전달.
        """
        return _report_result_impl(profile, action, fitness,
                                   code=code, stderr_tail=stderr_tail,
                                   attribution=attribution)

    @mcp.tool()
    def tc_explore_archive_state(profile: str) -> dict[str, Any]:
        """현재 archive 스냅샷(셀별 elite·n·mean + universals)."""
        return _archive_state_impl(profile)

    @mcp.tool()
    def tc_explore_build_query(profile: str) -> dict[str, Any]:
        """Explosion 모드 웹검색 쿼리 합성(placeholder, Phase D 본격화)."""
        return _build_query_impl(profile)


__all__ = ["register", "_recommend_action_impl", "_report_result_impl",
           "_archive_state_impl", "_build_query_impl"]
