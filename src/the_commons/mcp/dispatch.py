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
from the_commons.dispatcher.local_worker import LocalWorker


def _job_result_to_dict(r: JobResult) -> dict[str, Any]:
    """JobResult → MCP 응답 dict. stderr_tail은 항상 포함(V5/V11 자기수정 입력)."""
    return {
        "job_id": r.job_id, "workspace_id": r.workspace_id,
        "success": r.success, "fitness": r.fitness,
        "metrics": r.metrics, "describe": r.describe,
        "stderr_tail": r.stderr_tail, "error": r.error,
    }


def _build_worker(project_id: str, worker_id: str):
    """worker_id 기반 Worker 구현 선택.

    Phase C2: LocalWorker만. CqRemoteWorker는 Phase D2에서.
    구분은 환경/메타 기반: cq에서 워커 host == 로컬이면 LocalWorker, 아니면 원격 필요.
    당장은 LocalWorker만 — 원격 GPU(4090/3090) 사용은 D2 이후.
    """
    return LocalWorker(project_id=project_id, worker_id=worker_id)


def _dispatch_impl(
    profile: str, *, project_id: str, worker_id: str,
    name: str, code: str, command: str, monitor: str,
    aux_files: dict[str, str] | None = None,
    config: dict[str, Any] | None = None,
    metric_keys: list[str] | None = None,
    requirements: list[str] | None = None,
    timeout: int = 1200,
) -> dict[str, Any]:
    """JobSpec 조립 → 워커 dispatch → JobResult dict."""
    spec = JobSpec(
        name=name, code=code, command=command, monitor=monitor,
        aux_files=aux_files or {}, config=config or {},
        metric_keys=metric_keys or [monitor], requirements=requirements or [],
        timeout=timeout,
    )
    worker = _build_worker(project_id, worker_id)
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

        Returns:
          {job_id, workspace_id, success, fitness, metrics, describe,
           stderr_tail, error} — stderr_tail은 실패 시 에이전트 자기수정(V11) 입력.
        """
        return _dispatch_impl(
            profile, project_id=project_id, worker_id=worker_id,
            name=name, code=code, command=command, monitor=monitor,
            aux_files=aux_files, config=config, metric_keys=metric_keys,
            requirements=requirements, timeout=timeout,
        )


__all__ = ["register", "_dispatch_impl"]
