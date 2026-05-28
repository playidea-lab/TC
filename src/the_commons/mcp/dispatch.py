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


__all__ = ["register", "_dispatch_impl"]
