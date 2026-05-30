"""MCP 도구 — cq 워커에 코드 디스패치 + 결과 회수(stderr_tail 1급).

R1 Phase C2. tc_dispatch: JobSpec 명세를 받아 LocalWorker(현재) 또는 CqRemoteWorker
(Phase D2)로 보내고 JobResult를 반환.

worker_id로 LocalWorker/CqRemoteWorker 선택: cq에 등록된 모든 워커는 cq MCP RPC로
같은 인터페이스(create_job/control_job/get_status)를 노출하므로, "로컬 노트북"이냐
"원격 GPU"냐는 파일 시스템 접근(workspace 직접 read vs cq download)에서만 갈린다.
Phase D2까지는 LocalWorker만 사용(원격은 NotImplementedError).

core(_dispatch_impl)는 FastMCP 의존 없이 테스트 가능. mvtec smoke(LocalWorker, MPS Mac)로
회귀 검증, autoresearch smoke는 D5(GPU 워커 + CqRemoteWorker 완성 후).
"""

from __future__ import annotations

import os
from dataclasses import asdict
from typing import Any

from the_commons.dispatcher import JobResult, JobSpec, dispatch
from the_commons.dispatcher.cq_remote_worker import CqRemoteWorker
from the_commons.dispatcher.local_worker import LocalWorker
from the_commons.exploration.sandbox import (
    check_code as sandbox_check, is_blocked as sandbox_blocked,
    violations_to_dict,
)


def _job_result_to_dict(r: JobResult) -> dict[str, Any]:
    """JobResult → MCP 응답 dict. stderr_tail은 항상 포함(V5/V11 자기수정 입력)."""
    return {
        "job_id": r.job_id, "workspace_id": r.workspace_id,
        "success": r.success, "fitness": r.fitness,
        "metrics": r.metrics, "describe": r.describe,
        "stderr_tail": r.stderr_tail, "error": r.error,
    }


def _build_worker(project_id: str, worker_id: str, remote: bool = False):
    """worker_id 기반 Worker 구현 선택. remote=True면 CqRemoteWorker(원격 GPU),
    아니면 LocalWorker(워커=노트북, 공유 파일시스템). 호출자가 명시적으로 결정."""
    if remote:
        return CqRemoteWorker(project_id=project_id, worker_id=worker_id)
    return LocalWorker(project_id=project_id, worker_id=worker_id)


def _dispatch_impl(
    profile: str, *, project_id: str, worker_id: str,
    name: str, code: str, command: str, monitor: str,
    aux_files: dict[str, str] | None = None,
    config: dict[str, Any] | None = None,
    metric_keys: list[str] | None = None,
    requirements: list[str] | None = None,
    timeout: int = 1200,
    remote: bool = False,
) -> dict[str, Any]:
    """JobSpec 조립 → 워커 dispatch → JobResult dict."""
    # V8 sandbox 게이트: 디스패치 전 정적 검사 — 위반 시 GPU 비용 0으로 즉시 실패 반환.
    violations = sandbox_check(code)
    if sandbox_blocked(violations):
        first = next(v for v in violations if v.severity == "block")
        return {
            "job_id": "", "workspace_id": "",
            "success": False, "fitness": None, "metrics": {},
            "describe": None, "stderr_tail": "",
            "error": f"sandbox blocked ({first.rule}@L{first.line}): {first.message}",
            "sandbox_violations": violations_to_dict(violations),
        }

    spec = JobSpec(
        name=name, code=code, command=command, monitor=monitor,
        aux_files=aux_files or {}, config=config or {},
        metric_keys=metric_keys or [monitor], requirements=requirements or [],
        timeout=timeout,
    )
    worker = _build_worker(project_id, worker_id, remote=remote)
    try:
        result = dispatch(worker, spec)
    finally:
        worker.close()
    return _job_result_to_dict(result)


class _GenoView:
    """recommend dict의 genotype을 build_inject가 기대하는 .as_dict()로 노출."""

    def __init__(self, g: dict[str, Any]) -> None:
        self._c = dict(g["config"])      # config는 dict 또는 [[k,v],...] 둘 다 수용

    def as_dict(self) -> dict[str, float]:
        return dict(self._c)


class _ActionView:
    """build_inject(action)가 기대하는 .genotype·.seed 인터페이스(recommend dict 래핑)."""

    def __init__(self, action: dict[str, Any]) -> None:
        self.seed = int(action.get("seed", 0))
        self.genotype = _GenoView(action["genotype"])


def _dispatch_action_impl(
    profile: str, action: dict[str, Any], *, project_id: str, worker_id: str,
    name: str | None = None, remote: bool = False, timeout: int = 2700,
) -> dict[str, Any]:
    """profile + action(recommend 출력)만으로 dispatch 재료를 서버측 자동조립 후 디스패치.

    SKILL(Claude)은 파이썬 함수(RECIPE_SCRIPT·AUX·build_inject·build_command)를 실행 못
    하므로, 서버가 profile을 로드해 JobSpec을 구성한다(driver가 손으로 하던 조립 이식).
    tier2(새 recipe)면 호출자가 action.genotype을 새 recipe로 교체해 보낸 것을 그대로 쓴다.
    """
    from the_commons.exploration.session import load_profile
    P = load_profile(profile)
    geno = action["genotype"]
    recipe = geno["recipe"]
    code = Path(P.RECIPE_SCRIPT[recipe]).read_text()
    aux = {Path(f).name: Path(f).read_text() for f in getattr(P, "AUX_FILES", [])}
    inject = P.build_inject(_ActionView(action))
    config: dict[str, Any] = {"output_dir": ".", "monitor": P.MONITOR, "mode": "max", **inject}
    if hasattr(P, "DATA_ROOT"):
        config["data_root"] = P.DATA_ROOT
    job_name = name or f"{profile}-{P.recipe_arg(recipe)}"
    return _dispatch_impl(
        profile, project_id=project_id, worker_id=worker_id, name=job_name,
        code=code, command=P.build_command(), monitor=P.MONITOR,
        aux_files=aux, config=config, metric_keys=[P.METRIC],
        requirements=getattr(P, "REQS", []), timeout=timeout, remote=remote,
    )


def register(mcp) -> None:
    """FastMCP에 tc_dispatch 도구 등록."""

    @mcp.tool()
    def tc_dispatch(
        profile: str, project_id: str, worker_id: str,
        name: str, code: str, command: str, monitor: str,
        aux_files: dict[str, str] | None = None,
        config: dict[str, Any] | None = None,
        metric_keys: list[str] | None = None,
        requirements: list[str] | None = None,
        timeout: int = 1200,
        remote: bool = False,
    ) -> dict[str, Any]:
        """cq 워커에 코드 디스패치 + 결과 회수.

        Args:
          profile: 도메인 식별자(로깅용, 분기에 사용 안 함).
          project_id, worker_id: cq project/worker UUID.
          name: job 이름 prefix.
          code: train.py 본문(profile materialize 산출 또는 정적 파일 내용).
          command: 워커 shell command(profile build_command 결과 또는 default).
          monitor: cq best 판정 metric (= metric_keys[0] 기본).
          aux_files: name→content (예: autoresearch의 prepare.py).
          config: cq_config.json next_config (pcq.config() 주입).
          metric_keys: 회수 metric 키 (기본 [monitor]).
          requirements: pip reqs(uv run --with).
          timeout: poll 최대 대기(초).
          remote: True면 CqRemoteWorker(원격 GPU, NATS로 파일 입출력), False면
                  LocalWorker(워커=노트북, 공유 파일시스템). 기본 False(mvtec 후방호환).

        Returns:
          {job_id, workspace_id, success, fitness, metrics, describe,
           stderr_tail, error} — stderr_tail은 실패 시 에이전트 자기수정(V11) 입력.
        """
        return _dispatch_impl(
            profile, project_id=project_id, worker_id=worker_id,
            name=name, code=code, command=command, monitor=monitor,
            aux_files=aux_files, config=config, metric_keys=metric_keys,
            requirements=requirements, timeout=timeout, remote=remote,
        )

    @mcp.tool()
    def tc_dispatch_action(
        profile: str, action: dict[str, Any], project_id: str, worker_id: str,
        name: str | None = None, remote: bool = False, timeout: int = 2700,
    ) -> dict[str, Any]:
        """profile + action(recommend 출력)만으로 자동조립 디스패치(SKILL을 얇게).

        per-round SKILL은 recommend → tc_dispatch_action → report 3단계로 축소된다.
        서버가 profile에서 RECIPE_SCRIPT·AUX·build_inject·build_command를 조립한다.
        tier2면 호출자가 action.genotype을 새 recipe로 교체해 보낸다.
        """
        return _dispatch_action_impl(
            profile, action, project_id=project_id, worker_id=worker_id,
            name=name, remote=remote, timeout=timeout,
        )


__all__ = ["register", "_dispatch_impl", "_dispatch_action_impl"]
