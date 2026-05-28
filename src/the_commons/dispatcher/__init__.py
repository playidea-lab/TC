"""dispatcher_v2 — explore-loop v3의 워커-무관 디스패치 코어.

설계: [[explore-loop-v3-agent-in-loop]] (TheCommons idea V4·V5).

핵심 분리:
  - Worker (worker.py) — submit/poll/download/tail_stderr Protocol. 워커 토폴로지(로컬·원격) 추상.
  - JobSpec/JobResult (types.py) — 디스패치 계약. **stderr_tail은 1급 시민**(에이전트 자기수정 입력).
  - dispatch(worker, spec) — 워커 종류를 모르는 코어 흐름.

구현: LocalWorker(현 cq_dispatch 동작 흡수, mvtec/MPS), CqRemoteWorker(원격 GPU + cq download 회수).

이 패키지는 mvtec 회귀를 깨지 않는다 — 구 cq_dispatch.py는 그대로 두고 옆에 신설(D7에서 wrapper 격하 예정).
"""

from __future__ import annotations

import json

from .types import JobResult, JobSpec, RunStatus
from .worker import Worker

__all__ = ["JobSpec", "JobResult", "RunStatus", "Worker", "dispatch"]


def dispatch(worker: Worker, spec: JobSpec) -> JobResult:
    """워커-무관 디스패치 코어.

    흐름: submit → poll → describe.json·stderr 회수 → fitness 결정.

    fitness 우선순위(mvtec 정본 경로 계승):
      1) describe.json best_value (워크스페이스 파일, NATS 토큰 만료에 무관)
      2) metrics[spec.monitor] (cq get_status stdout 파싱 폴백)

    실패해도 stderr_tail은 채워 반환한다 — 에이전트가 그걸 보고 자기수정한다(V11).
    """
    try:
        job_id = worker.submit(spec)
    except Exception as e:                                   # 제출 자체 실패(네트워크/auth/...)
        return JobResult(job_id="", workspace_id="", success=False, fitness=None,
                         metrics={}, describe=None, stderr_tail="",
                         error=f"submit failed: {e}")

    ok, metrics, status_text = worker.poll(job_id, timeout=spec.timeout)
    describe_raw = worker.download(job_id, "describe.json")
    describe: dict | None = None
    if describe_raw:
        try:
            describe = json.loads(describe_raw)
        except (json.JSONDecodeError, ValueError):
            describe = None

    fitness: float | None = None
    if describe and "best_value" in describe:
        try:
            fitness = float(describe["best_value"])
        except (TypeError, ValueError):
            fitness = None
    elif spec.monitor and spec.monitor in metrics:
        try:
            fitness = float(metrics[spec.monitor])
        except (TypeError, ValueError):
            fitness = None

    stderr_tail = worker.tail_stderr(job_id) if not ok else ""

    return JobResult(job_id=job_id, workspace_id=job_id, success=ok, fitness=fitness,
                     metrics=metrics, describe=describe, stderr_tail=stderr_tail,
                     status_text=status_text, error="" if ok else _short_error(metrics, stderr_tail))


def _short_error(metrics: dict, stderr_tail: str) -> str:
    """실패 시 에이전트가 한눈에 보는 한 줄 요약."""
    if "error" in metrics:
        return str(metrics["error"])[:200]
    tail = stderr_tail.strip().splitlines()[-1:] if stderr_tail else []
    return tail[0][:200] if tail else "unknown failure"
